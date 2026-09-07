import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.models import Device


SDM_API_BASE = "https://smartdevicemanagement.googleapis.com/v1"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
TRAIT_CONNECTIVITY = "sdm.devices.traits.Connectivity"
TRAIT_HUMIDITY = "sdm.devices.traits.Humidity"
TRAIT_INFO = "sdm.devices.traits.Info"
TRAIT_SETTINGS = "sdm.devices.traits.Settings"
TRAIT_TEMPERATURE = "sdm.devices.traits.Temperature"
TRAIT_ECO = "sdm.devices.traits.ThermostatEco"
TRAIT_HVAC = "sdm.devices.traits.ThermostatHvac"
TRAIT_MODE = "sdm.devices.traits.ThermostatMode"
TRAIT_SETPOINT = "sdm.devices.traits.ThermostatTemperatureSetpoint"


class NestServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class MissingNestCredentialsError(NestServiceError):
    status_code = 400


class NestAuthError(NestServiceError):
    status_code = 401


class NestUnsupportedError(NestServiceError):
    status_code = 422


def _request_sync(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: Optional[dict[str, Any]] = None,
    form: Optional[dict[str, Any]] = None,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in (401, 403):
            raise NestAuthError(f"Google Nest token was rejected: {detail}") from exc
        raise NestServiceError(f"Google Nest API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise NestServiceError(f"Could not reach Google Nest API: {exc.reason}") from exc

    return json.loads(raw) if raw else {}


async def request(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: Optional[dict[str, Any]] = None,
    form: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(_request_sync, url, method=method, token=token, body=body, form=form)


async def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    authorization_code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return await request(
        OAUTH_TOKEN_URL,
        method="POST",
        form={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )


async def refresh_access_token(credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = credentials.get("refresh_token")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not refresh_token or not client_id or not client_secret:
        raise MissingNestCredentialsError("Nest refresh needs client_id, client_secret, and refresh_token.")

    payload = await request(
        OAUTH_TOKEN_URL,
        method="POST",
        form={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    credentials["access_token"] = payload.get("access_token")
    credentials["expires_at"] = int(time.time()) + int(payload.get("expires_in") or 3600)
    return credentials


async def access_token(credentials: dict[str, Any]) -> str:
    token = credentials.get("access_token")
    expires_at = int(credentials.get("expires_at") or 0)
    if token and (not expires_at or expires_at - time.time() > 60):
        return token
    refreshed = await refresh_access_token(credentials)
    token = refreshed.get("access_token")
    if not token:
        raise NestAuthError("Google did not return a Nest access token.")
    return token


def credentials_from_device(device: Device) -> dict[str, Any]:
    if not device.device_key:
        raise MissingNestCredentialsError("Nest credentials are missing for this device.")
    try:
        credentials = json.loads(device.device_key)
    except json.JSONDecodeError as exc:
        raise MissingNestCredentialsError("Nest credentials must be stored as JSON.") from exc
    if not credentials.get("project_id"):
        raise MissingNestCredentialsError("Nest project_id is missing.")
    return credentials


def credentials_to_device_key(project_id: str, token_payload: dict[str, Any], base: dict[str, Any]) -> str:
    credentials = {
        "project_id": project_id,
        "client_id": base.get("client_id"),
        "client_secret": base.get("client_secret"),
        "refresh_token": token_payload.get("refresh_token") or base.get("refresh_token"),
        "access_token": token_payload.get("access_token") or base.get("access_token"),
    }
    if token_payload.get("expires_in"):
        credentials["expires_at"] = int(time.time()) + int(token_payload["expires_in"])
    return json.dumps({key: value for key, value in credentials.items() if value})


async def list_devices(credentials: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = credentials.get("project_id")
    token = await access_token(credentials)
    payload = await request(f"{SDM_API_BASE}/enterprises/{urllib.parse.quote(project_id, safe='')}/devices", token=token)
    return payload.get("devices", [])


async def get_device(device: Device) -> dict[str, Any]:
    credentials = credentials_from_device(device)
    token = await access_token(credentials)
    return await request(f"{SDM_API_BASE}/{_device_name(device)}", token=token)


async def execute_command(device: Device, command: str, params: dict[str, Any]) -> dict[str, Any]:
    credentials = credentials_from_device(device)
    token = await access_token(credentials)
    return await request(
        f"{SDM_API_BASE}/{_device_name(device)}:executeCommand",
        method="POST",
        token=token,
        body={"command": command, "params": params},
    )


async def set_mode(device: Device, mode: str) -> dict[str, Any]:
    safe_mode = mode.upper()
    if safe_mode not in {"HEAT", "COOL", "HEATCOOL", "OFF"}:
        raise NestUnsupportedError("Nest mode must be HEAT, COOL, HEATCOOL, or OFF.")
    await execute_command(
        device,
        "sdm.devices.commands.ThermostatMode.SetMode",
        {"mode": safe_mode},
    )
    return await get_status(device)


async def set_heat(device: Device, heat_celsius: float) -> dict[str, Any]:
    await execute_command(
        device,
        "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat",
        {"heatCelsius": heat_celsius},
    )
    return await get_status(device)


async def set_cool(device: Device, cool_celsius: float) -> dict[str, Any]:
    await execute_command(
        device,
        "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool",
        {"coolCelsius": cool_celsius},
    )
    return await get_status(device)


async def set_range(device: Device, heat_celsius: float, cool_celsius: float) -> dict[str, Any]:
    if heat_celsius >= cool_celsius:
        raise NestUnsupportedError("Heat setpoint must be lower than cool setpoint.")
    await execute_command(
        device,
        "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange",
        {"heatCelsius": heat_celsius, "coolCelsius": cool_celsius},
    )
    return await get_status(device)


async def get_status(device: Device) -> dict[str, Any]:
    payload = await get_device(device)
    traits = payload.get("traits", {})
    connectivity = traits.get(TRAIT_CONNECTIVITY, {}).get("status")
    mode = traits.get(TRAIT_MODE, {}).get("mode")
    appliance = thermostat_summary(payload)
    return {
        "is_on": connectivity != "OFFLINE" and mode != "OFF",
        "appliance": appliance,
        "raw": payload,
    }


def thermostat_summary(payload: dict[str, Any]) -> dict[str, Any]:
    traits = payload.get("traits", {})
    info = traits.get(TRAIT_INFO, {})
    settings = traits.get(TRAIT_SETTINGS, {})
    temperature = traits.get(TRAIT_TEMPERATURE, {})
    humidity = traits.get(TRAIT_HUMIDITY, {})
    eco = traits.get(TRAIT_ECO, {})
    hvac = traits.get(TRAIT_HVAC, {})
    mode = traits.get(TRAIT_MODE, {})
    setpoint = traits.get(TRAIT_SETPOINT, {})
    return _remove_empty({
        "type": "thermostat",
        "title": "Nest thermostat",
        "customName": info.get("customName"),
        "temperatureScale": settings.get("temperatureScale"),
        "ambientCelsius": temperature.get("ambientTemperatureCelsius"),
        "ambientFahrenheit": c_to_f(temperature.get("ambientTemperatureCelsius")),
        "humidity": humidity.get("ambientHumidityPercent"),
        "mode": mode.get("mode"),
        "availableModes": mode.get("availableModes"),
        "hvacStatus": hvac.get("status"),
        "ecoMode": eco.get("mode"),
        "heatCelsius": setpoint.get("heatCelsius"),
        "heatFahrenheit": c_to_f(setpoint.get("heatCelsius")),
        "coolCelsius": setpoint.get("coolCelsius"),
        "coolFahrenheit": c_to_f(setpoint.get("coolCelsius")),
        "ecoHeatCelsius": eco.get("heatCelsius"),
        "ecoCoolCelsius": eco.get("coolCelsius"),
        "connectivity": traits.get(TRAIT_CONNECTIVITY, {}).get("status"),
    })


def is_thermostat(raw_device: dict[str, Any]) -> bool:
    traits = raw_device.get("traits", {})
    return TRAIT_MODE in traits or TRAIT_SETPOINT in traits or raw_device.get("type") == "sdm.devices.types.THERMOSTAT"


def display_name(raw_device: dict[str, Any]) -> str:
    traits = raw_device.get("traits", {})
    custom_name = traits.get(TRAIT_INFO, {}).get("customName")
    if custom_name:
        return custom_name
    relations = raw_device.get("parentRelations") or []
    for relation in relations:
        if relation.get("displayName"):
            return f"Nest Thermostat - {relation['displayName']}"
    return "Nest Thermostat"


def room_name(raw_device: dict[str, Any]) -> str | None:
    for relation in raw_device.get("parentRelations") or []:
        if relation.get("displayName"):
            return relation["displayName"]
    return None


def _device_name(device: Device) -> str:
    if device.device_uuid:
        return device.device_uuid
    if device.host.startswith("nest:"):
        return device.host.split(":", 1)[1]
    raise NestUnsupportedError("Nest device resource name is missing.")


def _remove_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None and value != ""}


def c_to_f(value: Any) -> float | None:
    if value is None:
        return None
    return round((float(value) * 9 / 5) + 32, 1)
