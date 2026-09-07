import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any
from urllib import error, request

from dotenv import load_dotenv

from app.models import Device


load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("MEROSS_REQUEST_TIMEOUT_SECONDS", "5"))


class MerossServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class MissingHostError(MerossServiceError):
    status_code = 400


class MissingDeviceKeyError(MerossServiceError):
    status_code = 400


class DeviceDisabledError(MerossServiceError):
    status_code = 409


class DeviceTimeoutError(MerossServiceError):
    status_code = 504


class DeviceUnreachableError(MerossServiceError):
    status_code = 502


class WrongDeviceKeyError(MerossServiceError):
    status_code = 401


class UnsupportedModelError(MerossServiceError):
    status_code = 422


def _validate_device(device: Device) -> None:
    if not device.is_enabled:
        raise DeviceDisabledError("Device is disabled.")
    if not device.host:
        raise MissingHostError("Device host is missing.")
    if not device.device_key:
        raise MissingDeviceKeyError("Device key is missing.")


def _sign(message_id: str, key: str, timestamp: int) -> str:
    return hashlib.md5(f"{message_id}{key}{timestamp}".encode("utf-8")).hexdigest()


def _build_message(namespace: str, method: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    message_id = uuid.uuid4().hex
    timestamp = int(time.time())
    return {
        "header": {
            "messageId": message_id,
            "namespace": namespace,
            "method": method,
            "payloadVersion": 1,
            "from": "/app/sentinel/subscribe",
            "timestamp": timestamp,
            "sign": _sign(message_id, key, timestamp),
            "triggerSrc": "Local",
        },
        "payload": payload,
    }


def _post_config_sync(host: str, body: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    url = f"http://{host}/config"
    encoded = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise DeviceTimeoutError(f"Timed out contacting {host}.") from exc
    except error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise DeviceTimeoutError(f"Timed out contacting {host}.") from exc
        raise DeviceUnreachableError(f"Could not reach device at {host}: {exc.reason}") from exc
    except OSError as exc:
        raise DeviceUnreachableError(f"Could not reach device at {host}: {exc}") from exc

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise UnsupportedModelError(f"Device at {host} returned non-JSON data.") from exc


async def _request_device(
    device: Device,
    namespace: str,
    method: str,
    payload: dict[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    _validate_device(device)
    assert device.device_key is not None

    body = _build_message(namespace, method, device.device_key, payload)
    logger.debug("Sending Meross %s %s to %s", method, namespace, device.host)
    response = await asyncio.to_thread(_post_config_sync, device.host, body, timeout_seconds)

    header = response.get("header", {})
    response_method = header.get("method")
    if response_method == "ERROR":
        error_payload = response.get("payload", {}).get("error", {})
        code = error_payload.get("code")
        detail = error_payload.get("detail", "Meross device returned an error.")
        if code == 5001 or "sign" in str(detail).lower():
            raise WrongDeviceKeyError("The device rejected the request signature. Check the device key.")
        raise MerossServiceError(f"Meross device returned error {code}: {detail}")

    return response


def _extract_onoff(response: dict[str, Any], channel: int) -> bool:
    payload = response.get("payload", {})

    # Appliance.System.All responses commonly carry state in payload.all.digest.togglex.
    digest = payload.get("all", {}).get("digest", {})
    toggles = digest.get("togglex") or digest.get("toggle") or []
    if isinstance(toggles, dict):
        toggles = [toggles]

    for item in toggles:
        if item.get("channel", 0) == channel:
            return bool(item.get("onoff"))

    # Appliance.Control.ToggleX responses commonly echo payload.togglex.
    togglex = payload.get("togglex") or payload.get("toggle")
    if isinstance(togglex, dict) and togglex.get("channel", 0) == channel:
        return bool(togglex.get("onoff"))

    raise UnsupportedModelError("Could not find smart-plug on/off state in the Meross response.")


def _extract_garage_open(response: dict[str, Any], channel: int) -> bool | None:
    doors = response.get("payload", {}).get("all", {}).get("digest", {}).get("garageDoor", [])
    if isinstance(doors, dict):
        doors = [doors]

    for door in doors:
        if door.get("channel", 0) == channel:
            return bool(door.get("open"))
    return None


def _extract_luminance(response: dict[str, Any], channel: int) -> int | None:
    payload = response.get("payload", {})
    light = payload.get("all", {}).get("digest", {}).get("light") or payload.get("light")
    if isinstance(light, dict) and light.get("channel", 0) == channel:
        luminance = light.get("luminance")
        return int(luminance) if luminance is not None else None
    return None


async def get_state(device: Device) -> dict[str, Any]:
    response = await _request_device(device, "Appliance.System.All", "GET", {})
    is_open = _extract_garage_open(response, device.channel)
    luminance = _extract_luminance(response, device.channel)
    try:
        is_on = _extract_onoff(response, device.channel)
    except UnsupportedModelError:
        is_on = bool(is_open) if is_open is not None else False
    return {"is_on": is_on, "is_open": is_open, "luminance": luminance, "raw": response}


async def _set_power(device: Device, onoff: bool) -> dict[str, Any]:
    payload = {"togglex": {"channel": device.channel, "onoff": 1 if onoff else 0}}
    response = await _request_device(device, "Appliance.Control.ToggleX", "SET", payload)

    try:
        is_on = _extract_onoff(response, device.channel)
    except UnsupportedModelError:
        is_on = onoff
    return {"is_on": is_on, "raw": response}


async def turn_on(device: Device) -> dict[str, Any]:
    return await _set_power(device, True)


async def turn_off(device: Device) -> dict[str, Any]:
    return await _set_power(device, False)


async def toggle(device: Device) -> dict[str, Any]:
    current = await get_state(device)
    return await _set_power(device, not current["is_on"])


async def garage_open(device: Device) -> dict[str, Any]:
    if not device.device_uuid:
        raise UnsupportedModelError("Garage operation requires device_uuid.")
    payload = {"state": {"channel": device.channel, "open": 1, "uuid": device.device_uuid}}
    response = await _request_device(device, "Appliance.GarageDoor.State", "SET", payload)
    return {"is_open": True, "is_on": True, "raw": response}


async def garage_close(device: Device) -> dict[str, Any]:
    if not device.device_uuid:
        raise UnsupportedModelError("Garage operation requires device_uuid.")
    payload = {"state": {"channel": device.channel, "open": 0, "uuid": device.device_uuid}}
    response = await _request_device(device, "Appliance.GarageDoor.State", "SET", payload)
    return {"is_open": False, "is_on": False, "raw": response}


async def set_brightness(device: Device, luminance: int) -> dict[str, Any]:
    if luminance < 1 or luminance > 100:
        raise UnsupportedModelError("Brightness must be between 1 and 100.")
    payload = {
        "light": {
            "channel": device.channel,
            "luminance": luminance,
            "capacity": 4,
            "gradual": 0,
        }
    }
    response = await _request_device(device, "Appliance.Control.Light", "SET", payload)
    return {"luminance": luminance, "is_on": True, "raw": response}
