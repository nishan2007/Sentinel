import asyncio
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pyhap.accessory_driver import AccessoryDriver

from app import db, homekit_db, homekit_service
from app.models import Device
from app.schemas import DeviceCreate


class HomeKitMappingTests(unittest.TestCase):
    def setUp(self):
        self.driver = AccessoryDriver(port=51998, persist_file=str(Path("data") / "homekit-test.state"))
        self.device = Device(1, "Test Plug", "meross", "MSS110", "127.0.0.1", "key", "uuid", "outlet", 0, True, None, "", "")

    def test_supported_profiles_build_valid_hap_accessories(self):
        profiles = ["outlet", "light", "lock", "garage-door", "thermostat", "heater-cooler", "motion-sensor", "contact-sensor", "smoke-sensor", "co-sensor", "leak-sensor"]
        for aid, profile in enumerate(profiles, 2):
            accessory = homekit_service._make_accessory(self.driver, replace(self.device, id=aid, name=profile), {"profile": profile, "aid": aid})
            self.assertIsNotNone(accessory)
            self.assertGreater(len(accessory.to_HAP(include_value=False)["services"]), 1)

    def test_device_classification(self):
        self.assertEqual(homekit_service.classify(self.device)[0], "outlet")
        self.assertEqual(homekit_service.classify(replace(self.device, brand="yale", device_type="lock"))[0], "lock")
        self.assertEqual(homekit_service.classify(replace(self.device, brand="ip-camera", device_type="camera"))[0], "camera")
        self.assertEqual(homekit_service.classify(replace(self.device, brand="milexus", device_type="air-conditioner"))[0], "heater-cooler")
        self.assertEqual(homekit_service.classify(replace(self.device, brand="tuya", device_type="climate"))[0], "heater-cooler")
        self.assertIsNone(homekit_service.classify(replace(self.device, name="Office Printer", model="GX", brand="printer", device_type="printer"))[0])

    def test_tuya_ac_state_maps_to_thermostat_characteristics(self):
        state = {"is_on": True, "appliance": {"mode": "cold", "currentTemperature": 26, "targetTemperature": 22, "fanSpeed": "strong", "verticalSwing": "1"}}
        self.assertEqual(homekit_service._state_value(state, "thermostat", "CurrentHeatingCoolingState"), 2)
        self.assertEqual(homekit_service._state_value(state, "thermostat", "TargetHeatingCoolingState"), 2)
        self.assertEqual(homekit_service._state_value(state, "thermostat", "CurrentTemperature"), 26)
        self.assertEqual(homekit_service._state_value(state, "thermostat", "TargetTemperature"), 22)
        self.assertEqual(homekit_service._state_value(state, "thermostat", "RotationSpeed"), 100)
        self.assertEqual(homekit_service._state_value(state, "thermostat", "SwingMode"), 1)

    def test_tuya_ac_uses_combined_heater_cooler_service(self):
        device = replace(self.device, id=22, name="Office AC", brand="tuya", device_type="climate")
        accessory = homekit_service._make_accessory(self.driver, device, {"profile": "heater-cooler", "aid": 22})
        services = {service.display_name: service for service in accessory.services}
        self.assertIn("HeaterCooler", services)
        names = {char.display_name for char in services["HeaterCooler"].characteristics}
        self.assertIn("RotationSpeed", names)
        self.assertIn("SwingMode", names)


class HomeKitTuyaWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_tuya_ac_accepts_homekit_mode_and_temperature(self):
        device = Device(2, "Bedroom AC", "milexus", "AC", "10.0.0.5", '{"local_key":"x"}', "uuid", "air-conditioner", 0, True, None, "", "")
        with patch.object(homekit_service.tuya_service, "set_values", new=AsyncMock()) as set_values:
            await homekit_service.write_value(device, "thermostat", "TargetHeatingCoolingState", 2)
            set_values.assert_awaited_once_with(device, {"power": True, "mode": "cold"})
            set_values.reset_mock()
            await homekit_service.write_value(device, "thermostat", "TargetTemperature", 23)
            set_values.assert_awaited_once_with(device, {"target_temperature": 23.0})
            set_values.reset_mock()
            await homekit_service.write_value(device, "thermostat", "RotationSpeed", 100)
            set_values.assert_awaited_once_with(device, {"fan_speed": "strong"})
            set_values.reset_mock()
            await homekit_service.write_value(device, "thermostat", "SwingMode", 1)
            set_values.assert_awaited_once_with(device, {"vertical_swing": "1"})


class HomeKitDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_path = db.DATABASE_PATH
        self.path = Path("data") / f"homekit-test-{uuid.uuid4().hex}.db"
        db.DATABASE_PATH = self.path
        await db.init_db()
        await homekit_db.init_homekit_db()

    async def asyncTearDown(self):
        db.DATABASE_PATH = self.old_path
        for suffix in ("", "-shm", "-wal"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()

    async def test_settings_and_stable_accessory_id(self):
        device = await db.create_device(DeviceCreate(name="Office Plug", brand="meross", host="10.0.0.2", device_type="outlet"))
        first = await homekit_db.ensure_accessory(device.id, "outlet")
        await homekit_db.update_accessory(device.id, enabled=False)
        second = await homekit_db.ensure_accessory(device.id, "outlet")
        self.assertEqual(first["aid"], second["aid"])
        self.assertFalse(second["enabled"])
        migrated = await homekit_db.ensure_accessory(device.id, "heater-cooler")
        self.assertEqual(migrated["profile"], "heater-cooler")
        await homekit_db.set_temperature_display_units(device.id, 1)
        fahrenheit = await homekit_db.get_accessory(device.id)
        self.assertEqual(fahrenheit["temperature_display_units"], 1)
        settings = await homekit_db.update_settings({"enabled": True, "bridge_name": "My Sentinel"})
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["bridge_name"], "My Sentinel")


if __name__ == "__main__":
    unittest.main()
