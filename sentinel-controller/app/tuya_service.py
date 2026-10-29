"""Local-LAN control for Tuya / Smart Life devices.

Credentials and datapoint mappings live in ``device.device_key`` as JSON.  No
Tuya account credentials are stored or used by this module.
"""

import asyncio
import json
import ipaddress
import time
from dataclasses import replace
from typing import Any

from app import db
from app.models import Device
from app.schemas import DeviceUpdate

_request_locks: dict[str, asyncio.Lock] = {}
_last_discovery: dict[str, float] = {}
_discovery_lock = asyncio.Lock()


def _discover_host(device: Device) -> str | None:
    from tinytuya.scanner import devices
    found = devices(verbose=False, scantime=4, poll=False, byID=True,
                    show_timer=False, tuyadevices=[])
    candidate = found.get(device.device_uuid, {}).get("ip")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return str(address) if address.version == 4 and not address.is_unspecified and not address.is_multicast else None


async def _request(device: Device, operation) -> dict[str, Any]:
    """Refresh stale HomeKit snapshots and recover only authenticated device IDs."""
    key = device.device_uuid or str(device.id)
    async with _request_locks.setdefault(key, asyncio.Lock()):
        saved = await db.get_device(device.id)
        if saved and saved.device_uuid == device.device_uuid:
            device = saved
        config = _config(device)
        try:
            return await asyncio.to_thread(lambda: _check_response(operation(_client(device, config))))
        except TuyaConfigurationError:
            raise
        except (TuyaServiceError, OSError) as original:
            async with _discovery_lock:
                if time.monotonic() - _last_discovery.get(key, float("-inf")) < 30:
                    raise original
                _last_discovery[key] = time.monotonic()
                try:
                    host = await asyncio.to_thread(_discover_host, device)
                except Exception:
                    raise original
            if not host or host == device.host:
                raise original
            candidate = replace(device, host=host)
            # A broadcast alone is not trusted. Authenticate a read with the
            # existing local key before saving an address or sending a command.
            verified = await asyncio.to_thread(lambda: _check_response(_client(candidate, config).status()))
            if not isinstance(verified.get("dps"), dict) or not verified["dps"]:
                raise original
            latest = await db.get_device(device.id)
            if not latest or latest.device_uuid != device.device_uuid or latest.host != device.host:
                raise original
            await db.update_device(device.id, DeviceUpdate(host=host))
            return await asyncio.to_thread(lambda: _check_response(operation(_client(candidate, config))))


class TuyaServiceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class TuyaConfigurationError(TuyaServiceError):
    def __init__(self, message: str):
        super().__init__(message, 422)


TCL_AC_DPS = {
    "power": "1", "target_temperature": "2", "current_temperature": "3",
    "mode": "4", "fan_speed": "5", "sleep": "105", "swing": "105",
    "vertical_swing": "113", "horizontal_swing": "114", "energy_saver": "119",
    "gen_mode": "120", "features": "123", "vertical_airflow": "126",
    "horizontal_airflow": "127", "power_limit": "129",
    "energy_saver_temperature": "130", "temperature_airflow": "132",
    "combined_swing": "133",
}


def _config(device: Device) -> dict[str, Any]:
    if not device.host or not device.device_uuid or not device.device_key:
        raise TuyaConfigurationError(
            "Tuya LAN control requires host, device_uuid (Tuya device ID), and device_key configuration."
        )
    try:
        config = json.loads(device.device_key)
    except json.JSONDecodeError as exc:
        raise TuyaConfigurationError("Tuya device_key must be a JSON object.") from exc
    if not isinstance(config, dict) or not config.get("local_key"):
        raise TuyaConfigurationError("Tuya device_key JSON must contain local_key.")
    mappings = config.get("dps", {})
    if not isinstance(mappings, dict):
        raise TuyaConfigurationError("Tuya dps configuration must be a JSON object.")
    if device.model == "hw50w7qvxluhslkk":
        mappings = dict(mappings)
        for name, dp in TCL_AC_DPS.items():
            mappings.setdefault(name, dp)
        config["dps"] = mappings
    return config


def _client(device: Device, config: dict[str, Any]):
    try:
        import tinytuya
    except ImportError as exc:
        raise TuyaConfigurationError(
            "TinyTuya is not installed. Reinstall Sentinel requirements and restart Sentinel."
        ) from exc
    try:
        client = tinytuya.Device(
            device.device_uuid,
            device.host,
            config["local_key"],
            version=float(config.get("version", 3.3)),
        )
        client.set_socketTimeout(float(config.get("timeout_seconds", 2)))
        client.set_socketRetryLimit(1)
        client.set_socketPersistent(False)
        return client
    except (TypeError, ValueError) as exc:
        raise TuyaConfigurationError(f"Invalid Tuya LAN configuration: {exc}") from exc


def _check_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise TuyaServiceError("Tuya device returned an invalid response.")
    if response.get("Error") or response.get("Err"):
        message = response.get("Error") or response.get("Err")
        raise TuyaServiceError(f"Tuya device rejected the LAN request: {message}")
    return response


def _mapped_value(dps: dict[str, Any], mapping: dict[str, Any], name: str) -> Any:
    dp = mapping.get(name)
    if dp is None:
        return None
    return dps.get(str(dp), dps.get(dp))


def _temperature(value: Any, config: dict[str, Any], name: str) -> Any:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    divisor = config.get(f"{name}_divisor", config.get("temperature_divisor", 1))
    return value / float(divisor)


def _feature_flags(value: Any) -> int:
    try:
        return int(str(value or "0"), 16)
    except ValueError:
        return 0


def _feature_enabled(value: Any, bit: int) -> bool:
    return bool(_feature_flags(value) & (1 << bit))


async def get_state(device: Device) -> dict[str, Any]:
    config = _config(device)

    try:
        response = await _request(device, lambda client: client.status())
    except TuyaServiceError:
        raise
    except TimeoutError as exc:
        raise TuyaServiceError("Tuya device timed out on the local network.", 504) from exc
    except OSError as exc:
        raise TuyaServiceError(f"Tuya device is unreachable on the local network: {exc}", 503) from exc
    dps = response.get("dps") if isinstance(response.get("dps"), dict) else {}
    mapping = config.get("dps", {})
    power = _mapped_value(dps, mapping, "power")
    features = _mapped_value(dps, mapping, "features")
    appliance = {
        "kind": "air-conditioner",
        "source": "tuya-lan",
        "mode": _mapped_value(dps, mapping, "mode"),
        "targetTemperature": _temperature(_mapped_value(dps, mapping, "target_temperature"), config, "target_temperature"),
        "currentTemperature": _temperature(_mapped_value(dps, mapping, "current_temperature"), config, "current_temperature"),
        "fanSpeed": _mapped_value(dps, mapping, "fan_speed"),
        "swing": _mapped_value(dps, mapping, "swing"),
        "sleep": _mapped_value(dps, mapping, "sleep"),
        "verticalSwing": _mapped_value(dps, mapping, "vertical_swing"),
        "horizontalSwing": _mapped_value(dps, mapping, "horizontal_swing"),
        "verticalAirflow": _mapped_value(dps, mapping, "vertical_airflow"),
        "horizontalAirflow": _mapped_value(dps, mapping, "horizontal_airflow"),
        "energySaver": _mapped_value(dps, mapping, "energy_saver"),
        "genMode": _mapped_value(dps, mapping, "gen_mode"),
        "powerLimit": _mapped_value(dps, mapping, "power_limit"),
        "energySaverTemperature": _mapped_value(dps, mapping, "energy_saver_temperature"),
        "temperatureAirflow": _mapped_value(dps, mapping, "temperature_airflow"),
        "combinedSwing": _mapped_value(dps, mapping, "combined_swing"),
        "eco": _feature_enabled(features, 0),
        "health": _feature_enabled(features, 5),
        "gentleWind": _feature_enabled(features, 15),
    }
    return {"is_on": bool(power), "appliance": appliance, "raw": response}


async def set_values(device: Device, values: dict[str, Any]) -> dict[str, Any]:
    config = _config(device)
    mapping = config.get("dps", {})
    payload: dict[str, Any] = {}
    feature_changes = {name: values.pop(name) for name in ("eco", "health", "gentle_wind") if name in values}
    if feature_changes:
        current_response = await _request(device, lambda client: client.status())
        current_dps = current_response.get("dps") if isinstance(current_response.get("dps"), dict) else {}
        flags = _feature_flags(_mapped_value(current_dps, mapping, "features"))
        feature_bits = {"eco": 0, "health": 5, "gentle_wind": 15}
        for name, enabled in feature_changes.items():
            bit = feature_bits[name]
            flags = flags | (1 << bit) if enabled else flags & ~(1 << bit)
        features_dp = mapping.get("features")
        if features_dp is None:
            raise TuyaConfigurationError("No Tuya datapoint is configured for features.")
        payload[str(features_dp)] = f"{flags:04X}"

    for name, value in values.items():
        dp = mapping.get(name)
        if dp is None:
            raise TuyaConfigurationError(f"No Tuya datapoint is configured for {name}.")
        if name == "target_temperature":
            divisor = config.get("target_temperature_divisor", config.get("temperature_divisor", 1))
            value = round(float(value) * float(divisor))
        payload[str(dp)] = value
    if not payload:
        raise TuyaConfigurationError("At least one Tuya value is required.")

    try:
        await _request(device, lambda client: client.set_multiple_values(payload))
    except TuyaServiceError:
        raise
    except TimeoutError as exc:
        raise TuyaServiceError("Tuya device timed out on the local network.", 504) from exc
    except OSError as exc:
        raise TuyaServiceError(f"Tuya device is unreachable on the local network: {exc}", 503) from exc
    return await get_state(device)


async def turn_on(device: Device) -> dict[str, Any]:
    return await set_values(device, {"power": True})


async def turn_off(device: Device) -> dict[str, Any]:
    return await set_values(device, {"power": False})


async def toggle(device: Device) -> dict[str, Any]:
    state = await get_state(device)
    return await set_values(device, {"power": not state["is_on"]})
