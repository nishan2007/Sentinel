from typing import Any

import aiohttp
from yalexs.api_async import ApiAsync
from yalexs.const import Brand
from yalexs.exceptions import AugustApiAIOHTTPError

from app.models import Device


class YaleServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class MissingYaleTokenError(YaleServiceError):
    status_code = 400


class YaleAuthError(YaleServiceError):
    status_code = 401


def _token(device: Device) -> str:
    if not device.device_key:
        raise MissingYaleTokenError("Yale access token is missing for this device.")
    return device.device_key


def _brand(device: Device) -> Brand:
    if device.model and device.model in {item.value for item in Brand}:
        return Brand(device.model)
    return Brand.YALE_ACCESS


async def _api(device: Device) -> tuple[aiohttp.ClientSession, ApiAsync]:
    session = aiohttp.ClientSession()
    return session, ApiAsync(session, brand=_brand(device))


def _lock_id(device: Device) -> str:
    if device.device_uuid:
        return device.device_uuid
    if device.host.startswith("yale:"):
        return device.host.split(":", 1)[1]
    raise YaleServiceError("Yale lock ID is missing.")


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))


async def get_status(device: Device) -> dict[str, Any]:
    session, api = await _api(device)
    try:
        door_status, lock_status = await api.async_get_lock_door_status(_token(device), _lock_id(device), lock_status=True)
    except AugustApiAIOHTTPError as exc:
        if exc.auth_failed:
            raise YaleAuthError("Yale token was rejected. Re-import Yale devices with a fresh access token.") from exc
        raise YaleServiceError(f"Yale API error: {exc}") from exc
    finally:
        await session.close()

    lock_value = _enum_value(lock_status)
    door_value = _enum_value(door_status)
    return {
        "is_on": lock_value == "locked",
        "is_open": True if door_value == "open" else False if door_value == "closed" else None,
        "raw": {
            "lock_status": lock_value,
            "door_status": door_value,
        },
    }


async def lock(device: Device) -> dict[str, Any]:
    session, api = await _api(device)
    try:
        status = await api.async_lock(_token(device), _lock_id(device))
    except AugustApiAIOHTTPError as exc:
        if exc.auth_failed:
            raise YaleAuthError("Yale token was rejected. Re-import Yale devices with a fresh access token.") from exc
        raise YaleServiceError(f"Yale API error: {exc}") from exc
    finally:
        await session.close()
    return {"is_on": _enum_value(status) == "locked", "raw": {"lock_status": _enum_value(status)}}


async def unlock(device: Device) -> dict[str, Any]:
    session, api = await _api(device)
    try:
        status = await api.async_unlock(_token(device), _lock_id(device))
    except AugustApiAIOHTTPError as exc:
        if exc.auth_failed:
            raise YaleAuthError("Yale token was rejected. Re-import Yale devices with a fresh access token.") from exc
        raise YaleServiceError(f"Yale API error: {exc}") from exc
    finally:
        await session.close()
    return {"is_on": _enum_value(status) == "locked", "raw": {"lock_status": _enum_value(status)}}
