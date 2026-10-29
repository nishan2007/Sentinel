import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from app import tuya_service
from app.models import Device


def make_device():
    return Device(
        id=1, name="Milexus AC", brand="milexus", model="Smart WiFi AC",
        host="192.168.1.50", device_uuid="abc123", device_type="air-conditioner",
        device_key=json.dumps({
            "local_key": "0123456789abcdef", "version": 3.3,
            "temperature_divisor": 10,
            "dps": {"power": "1", "mode": "2", "target_temperature": "3",
                    "current_temperature": "4", "fan_speed": "5", "swing": "8"},
        }),
        channel=0, is_enabled=True, last_state=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class TuyaServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tuya_service._request_locks.clear()
        tuya_service._last_discovery.clear()
        self.saved = patch.object(tuya_service.db, "get_device", new_callable=AsyncMock)
        self.get_saved = self.saved.start()
        self.get_saved.return_value = None
        self.addCleanup(self.saved.stop)

    async def test_changed_ip_is_verified_saved_and_command_retried(self):
        device = make_device()
        self.get_saved.return_value = device
        old, new = MagicMock(), MagicMock()
        old.set_multiple_values.return_value = {"Error": "Network Error"}
        new.status.return_value = {"dps": {"1": True}}
        new.set_multiple_values.return_value = {"dps": {"1": True}}
        with patch.object(tuya_service, "_client", side_effect=lambda d, c: old if d.host == device.host else new), patch.object(
            tuya_service, "_discover_host", return_value="192.168.1.51"
        ), patch.object(tuya_service.db, "update_device", new_callable=AsyncMock) as update:
            await tuya_service._request(device, lambda client: client.set_multiple_values({"1": True}))
        new.status.assert_called_once()
        new.set_multiple_values.assert_called_once_with({"1": True})
        self.assertEqual(update.await_args.args[1].host, "192.168.1.51")

    async def test_unverified_address_is_not_saved_or_commanded(self):
        device = make_device()
        self.get_saved.return_value = device
        old, new = MagicMock(), MagicMock()
        old.set_multiple_values.return_value = {"Error": "Network Error"}
        new.status.return_value = {"Error": "Invalid key"}
        with patch.object(tuya_service, "_client", side_effect=[old, new]), patch.object(
            tuya_service, "_discover_host", return_value="192.168.1.51"
        ), patch.object(tuya_service.db, "update_device", new_callable=AsyncMock) as update:
            with self.assertRaises(tuya_service.TuyaServiceError):
                await tuya_service._request(device, lambda client: client.set_multiple_values({"1": True}))
        update.assert_not_awaited()
        new.set_multiple_values.assert_not_called()

    async def test_failed_discovery_is_throttled(self):
        client = MagicMock()
        client.status.return_value = {"Error": "Network Error"}
        with patch.object(tuya_service, "_client", return_value=client), patch.object(
            tuya_service, "_discover_host", return_value=None
        ) as discover:
            for _ in range(2):
                with self.assertRaises(tuya_service.TuyaServiceError):
                    await tuya_service.get_state(make_device())
        discover.assert_called_once()

    def test_discovery_matches_permanent_id_not_product_model(self):
        with patch("tinytuya.scanner.devices", return_value={
            "other-device": {"ip": "192.168.1.60"},
            "abc123": {"ip": "192.168.1.51"},
        }):
            self.assertEqual(tuya_service._discover_host(make_device()), "192.168.1.51")
        with patch("tinytuya.scanner.devices", return_value={
            "other-device": {"ip": "192.168.1.60"},
        }):
            self.assertIsNone(tuya_service._discover_host(make_device()))

    async def test_homekit_snapshot_uses_current_saved_address(self):
        self.get_saved.return_value = replace(make_device(), host="192.168.1.51")
        client = MagicMock()
        client.status.return_value = {"dps": {"1": True}}
        with patch.object(tuya_service, "_client", return_value=client) as factory:
            await tuya_service.get_state(make_device())
        self.assertEqual(factory.call_args.args[0].host, "192.168.1.51")

    async def test_state_maps_ac_datapoints(self):
        client = MagicMock()
        client.status.return_value = {
            "dps": {"1": True, "2": "cold", "3": 240, "4": 275, "5": "auto"}
        }
        with patch.object(tuya_service, "_client", return_value=client):
            state = await tuya_service.get_state(make_device())
        self.assertTrue(state["is_on"])
        self.assertEqual(state["appliance"]["targetTemperature"], 24)
        self.assertEqual(state["appliance"]["currentTemperature"], 27.5)
        self.assertEqual(state["appliance"]["mode"], "cold")

    async def test_command_translates_names_and_temperature(self):
        client = MagicMock()
        client.set_multiple_values.return_value = {"dps": {"1": True}}
        client.status.return_value = {"dps": {"1": True, "3": 230}}
        with patch.object(tuya_service, "_client", return_value=client):
            state = await tuya_service.set_values(
                make_device(), {"power": True, "target_temperature": 23}
            )
        client.set_multiple_values.assert_called_once_with({"1": True, "3": 230})
        self.assertTrue(state["is_on"])

    async def test_missing_mapping_is_safe(self):
        with self.assertRaises(tuya_service.TuyaConfigurationError):
            await tuya_service.set_values(make_device(), {"unknown": "x"})

    async def test_feature_flags_preserve_existing_bits(self):
        config = json.loads(make_device().device_key)
        config["dps"]["features"] = "123"
        device = replace(make_device(), device_key=json.dumps(config))
        client = MagicMock()
        client.status.side_effect = [
            {"dps": {"1": True, "123": "0018"}},
            {"dps": {"1": True, "123": "0039"}},
        ]
        client.set_multiple_values.return_value = {"dps": {"123": "0039"}}
        with patch.object(tuya_service, "_client", return_value=client):
            state = await tuya_service.set_values(device, {"eco": True, "health": True})
        client.set_multiple_values.assert_called_once_with({"123": "0039"})
        self.assertTrue(state["appliance"]["eco"])
        self.assertTrue(state["appliance"]["health"])

    async def test_plaintext_key_is_rejected(self):
        item = replace(make_device(), device_key="not-json")
        with self.assertRaises(tuya_service.TuyaConfigurationError):
            await tuya_service.get_state(item)


if __name__ == "__main__":
    unittest.main()
