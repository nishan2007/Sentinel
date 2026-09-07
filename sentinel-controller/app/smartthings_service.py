import asyncio
import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.models import Device


logger = logging.getLogger(__name__)

API_BASE = "https://api.smartthings.com/v1"
OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"
OAUTH_CREDENTIAL_CACHE: dict[str, dict[str, Any]] = {}
UPDATED_DEVICE_CREDENTIALS: dict[int, dict[str, Any]] = {}


class SmartThingsServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class MissingSmartThingsTokenError(SmartThingsServiceError):
    status_code = 400


class SmartThingsAuthError(SmartThingsServiceError):
    status_code = 401


class SmartThingsUnsupportedError(SmartThingsServiceError):
    status_code = 422


HIDDEN_DASHBOARD_COMMAND_CAPABILITIES = {
    "execute",
    "ocf",
    "refresh",
    "samsungce.softwareUpdate",
}


def _request_sync(
    token: str,
    path: str,
    method: str = "GET",
    body: Optional[dict[str, Any]] = None,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SmartThingsAuthError("SmartThings token was rejected. Check token scopes and expiration.") from exc
        detail = exc.read().decode("utf-8", errors="replace")
        raise SmartThingsServiceError(f"SmartThings API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SmartThingsServiceError(f"Could not reach SmartThings API: {exc.reason}") from exc

    if not raw:
        return {}
    return json.loads(raw)


async def request(token: str, path: str, method: str = "GET", body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not token:
        raise MissingSmartThingsTokenError("SmartThings token is missing.")
    return await asyncio.to_thread(_request_sync, token, path, method, body)


def _oauth_request_sync(
    *,
    client_id: str,
    client_secret: str,
    form: dict[str, Any],
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    data = urllib.parse.urlencode({key: value for key, value in form.items() if value is not None}).encode("utf-8")
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in (400, 401, 403):
            if form.get("grant_type") == "refresh_token" and "invalid_grant" in detail:
                raise SmartThingsAuthError(
                    "SmartThings refresh token is no longer valid. Sign in with SmartThings again; Sentinel will save the new rotating token for all SmartThings devices."
                ) from exc
            raise SmartThingsAuthError(f"SmartThings OAuth token request was rejected: {detail}") from exc
        raise SmartThingsServiceError(f"SmartThings OAuth error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SmartThingsServiceError(f"Could not reach SmartThings OAuth API: {exc.reason}") from exc

    return json.loads(raw) if raw else {}


async def oauth_request(*, client_id: str, client_secret: str, form: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(
        _oauth_request_sync,
        client_id=client_id,
        client_secret=client_secret,
        form=form,
    )


async def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    authorization_code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return await oauth_request(
        client_id=client_id,
        client_secret=client_secret,
        form={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": authorization_code,
            "redirect_uri": redirect_uri,
        },
    )


async def refresh_access_token(credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = credentials.get("refresh_token")
    client_id = credentials.get("client_id")
    client_secret = credentials.get("client_secret")
    if not refresh_token or not client_id or not client_secret:
        raise MissingSmartThingsTokenError("SmartThings refresh needs client_id, client_secret, and refresh_token.")

    payload = await oauth_request(
        client_id=client_id,
        client_secret=client_secret,
        form={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )
    credentials["access_token"] = payload.get("access_token")
    credentials["refresh_token"] = payload.get("refresh_token") or refresh_token
    credentials["expires_at"] = int(time.time()) + int(payload.get("expires_in") or 86400)
    return credentials


async def access_token(credentials: dict[str, Any]) -> str:
    token = credentials.get("access_token")
    expires_at = int(credentials.get("expires_at") or 0)
    if token and (not expires_at or expires_at - time.time() > 60):
        return token
    refreshed = await refresh_access_token(credentials)
    token = refreshed.get("access_token")
    if not token:
        raise SmartThingsAuthError("SmartThings did not return an access token.")
    return token


def credentials_from_secret(secret: str) -> dict[str, Any]:
    try:
        parsed = json.loads(secret)
    except json.JSONDecodeError:
        return {"access_token": secret, "pat": True}
    if not isinstance(parsed, dict):
        raise MissingSmartThingsTokenError("Stored SmartThings credentials have the wrong shape.")
    return parsed


def _oauth_cache_key(credentials: dict[str, Any]) -> str | None:
    client_id = credentials.get("client_id")
    return str(client_id) if client_id else None


def _safe_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in credentials.items()
        if key in {"client_id", "client_secret", "refresh_token", "access_token", "expires_at"} and value
    }


def _merge_cached_credentials(credentials: dict[str, Any]) -> bool:
    cache_key = _oauth_cache_key(credentials)
    if not cache_key or cache_key not in OAUTH_CREDENTIAL_CACHE:
        return False
    cached = OAUTH_CREDENTIAL_CACHE[cache_key]
    changed = False
    for key in ("refresh_token", "access_token", "expires_at"):
        if cached.get(key) and credentials.get(key) != cached.get(key):
            credentials[key] = cached[key]
            changed = True
    return changed


def _remember_credentials(device_id: int, credentials: dict[str, Any]) -> None:
    safe = _safe_credentials(credentials)
    cache_key = _oauth_cache_key(safe)
    if not cache_key:
        return
    OAUTH_CREDENTIAL_CACHE[cache_key] = dict(safe)
    UPDATED_DEVICE_CREDENTIALS[device_id] = dict(safe)


def updated_credentials_for_device(device_id: int) -> dict[str, Any] | None:
    credentials = UPDATED_DEVICE_CREDENTIALS.get(device_id)
    return dict(credentials) if credentials else None


def credentials_to_device_key(token_payload: dict[str, Any], base: dict[str, Any]) -> str:
    credentials = {
        "client_id": base.get("client_id"),
        "client_secret": base.get("client_secret"),
        "refresh_token": token_payload.get("refresh_token") or base.get("refresh_token"),
        "access_token": token_payload.get("access_token") or base.get("access_token"),
        "expires_at": token_payload.get("expires_at") or base.get("expires_at"),
    }
    if token_payload.get("expires_in"):
        credentials["expires_at"] = int(time.time()) + int(token_payload["expires_in"])
    return json.dumps({key: value for key, value in credentials.items() if value})


async def token_from_device(device: Device) -> str:
    if not device.device_key:
        raise MissingSmartThingsTokenError("SmartThings token is missing for this device.")
    credentials = credentials_from_secret(device.device_key)
    if credentials.get("pat"):
        return str(credentials.get("access_token") or "")
    original = _safe_credentials(credentials)
    merged_cached = _merge_cached_credentials(credentials)
    token = await access_token(credentials)
    if merged_cached or _safe_credentials(credentials) != original:
        _remember_credentials(device.id, credentials)
    return token


def _request_bytes_sync(token: str, urls: list[str], timeout_seconds: float = 12) -> tuple[bytes, str]:
    last_error = "SmartThings image endpoint did not return an image."
    for url in urls:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "image/jpeg,application/octet-stream,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                content_type = response.headers.get("content-type") or "image/jpeg"
                data = response.read()
                if data and (content_type.startswith("image/") or data.startswith(b"\xff\xd8")):
                    return data, content_type if content_type.startswith("image/") else "image/jpeg"
                last_error = f"{url} returned {content_type}."
        except urllib.error.HTTPError as exc:
            last_error = f"{url} returned HTTP {exc.code}."
        except urllib.error.URLError as exc:
            last_error = f"{url} failed: {exc.reason}."
    raise SmartThingsServiceError(last_error)


async def request_bytes(token: str, urls: list[str]) -> tuple[bytes, str]:
    if not token:
        raise MissingSmartThingsTokenError("SmartThings token is missing.")
    return await asyncio.to_thread(_request_bytes_sync, token, urls)


def _component_id(device: Device) -> str:
    return "main"


def _device_id(device: Device) -> str:
    if device.device_uuid:
        return device.device_uuid
    if device.host.startswith("smartthings:"):
        return device.host.split(":", 1)[1]
    raise SmartThingsUnsupportedError("SmartThings device ID is missing.")


async def list_devices(token: str) -> list[dict[str, Any]]:
    payload = await request(token, "/devices")
    return payload.get("items", [])


async def get_device_detail(device: Device) -> dict[str, Any]:
    return await request(await token_from_device(device), f"/devices/{_device_id(device)}")


async def get_capability_metadata(token: str, capability_id: str, version: int | str | None) -> dict[str, Any] | None:
    if version is None:
        return None
    safe_capability = urllib.parse.quote(str(capability_id), safe="")
    safe_version = urllib.parse.quote(str(version), safe="")
    try:
        return await request(token, f"/capabilities/{safe_capability}/{safe_version}")
    except SmartThingsServiceError:
        logger.info("Could not load SmartThings capability metadata for %s/%s", capability_id, version, exc_info=True)
        return None


def _command_summary(command_name: str, command_spec: Any) -> dict[str, Any]:
    if not isinstance(command_spec, dict):
        return {"name": command_name, "arguments": []}

    arguments = []
    for arg in command_spec.get("arguments", []) or []:
        if not isinstance(arg, dict):
            continue
        schema = arg.get("schema", {}) if isinstance(arg.get("schema"), dict) else {}
        argument = {
            "name": arg.get("name"),
            "optional": bool(arg.get("optional")),
            "type": schema.get("type"),
        }
        if "enum" in schema:
            argument["options"] = schema.get("enum")
        if "minimum" in schema:
            argument["minimum"] = schema.get("minimum")
        if "maximum" in schema:
            argument["maximum"] = schema.get("maximum")
        arguments.append(_remove_empty(argument))

    return {"name": command_name, "arguments": arguments}


def _attribute_summary(attribute_name: str, attribute_spec: Any) -> dict[str, Any]:
    if not isinstance(attribute_spec, dict):
        return {"name": attribute_name}

    schema = attribute_spec.get("schema", {}) if isinstance(attribute_spec.get("schema"), dict) else {}
    summary = {
        "name": attribute_name,
        "type": schema.get("type"),
    }
    if "enum" in schema:
        summary["options"] = schema.get("enum")
    if "minimum" in schema:
        summary["minimum"] = schema.get("minimum")
    if "maximum" in schema:
        summary["maximum"] = schema.get("maximum")
    return _remove_empty(summary)


def _metadata_summary(capability_id: str, version: int | str | None, component_id: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {
            "component": component_id,
            "id": capability_id,
            "version": version,
            "commands": [],
            "attributes": [],
            "metadataAvailable": False,
        }

    commands = [
        _command_summary(name, spec)
        for name, spec in sorted((metadata.get("commands") or {}).items())
    ]
    attributes = [
        _attribute_summary(name, spec)
        for name, spec in sorted((metadata.get("attributes") or {}).items())
    ]
    return {
        "component": component_id,
        "id": capability_id,
        "version": version,
        "name": metadata.get("name"),
        "commands": commands,
        "attributes": attributes,
        "metadataAvailable": True,
    }


async def inspect_capabilities(device: Device) -> dict[str, Any]:
    detail = await get_device_detail(device)
    token = await token_from_device(device)
    capabilities = []

    for component in detail.get("components", []) or []:
        component_id = component.get("id") or "main"
        for capability in component.get("capabilities", []) or []:
            capability_id = capability.get("id")
            if not capability_id:
                continue
            version = capability.get("version")
            metadata = await get_capability_metadata(token, capability_id, version)
            capabilities.append(_metadata_summary(capability_id, version, component_id, metadata))

    controllable = [cap for cap in capabilities if cap.get("commands")]
    status_only = [cap for cap in capabilities if not cap.get("commands")]
    return {
        "deviceId": detail.get("deviceId") or _device_id(device),
        "name": detail.get("label") or detail.get("name") or device.name,
        "model": detail.get("deviceTypeName") or detail.get("type") or device.model,
        "controllable": controllable,
        "statusOnly": status_only,
        "capabilityCount": len(capabilities),
    }


async def validate_command(device: Device, component: str, capability: str, command: str, arguments: list[Any]) -> None:
    if capability in HIDDEN_DASHBOARD_COMMAND_CAPABILITIES:
        raise SmartThingsUnsupportedError(f"{capability}.{command} is intentionally hidden from dashboard execution.")

    inspection = await inspect_capabilities(device)
    for cap in inspection.get("controllable", []):
        if cap.get("component") != component or cap.get("id") != capability:
            continue
        for available_command in cap.get("commands", []):
            if available_command.get("name") != command:
                continue
            validate_arguments(available_command.get("arguments", []), arguments)
            return

    raise SmartThingsUnsupportedError(f"{capability}.{command} is not exposed as a controllable command for this device.")


def validate_arguments(argument_specs: list[dict[str, Any]], values: list[Any]) -> None:
    required_count = len([spec for spec in argument_specs if not spec.get("optional")])
    if len(values) < required_count:
        raise SmartThingsUnsupportedError(f"Command requires at least {required_count} argument(s).")
    if len(values) > len(argument_specs):
        raise SmartThingsUnsupportedError(f"Command accepts at most {len(argument_specs)} argument(s).")

    for index, value in enumerate(values):
        spec = argument_specs[index]
        options = spec.get("options")
        if options and value not in options:
            raise SmartThingsUnsupportedError(f"Argument {spec.get('name') or index + 1} must be one of: {', '.join(map(str, options))}.")

        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if (minimum is not None or maximum is not None) and isinstance(value, (int, float)):
            if minimum is not None and value < minimum:
                raise SmartThingsUnsupportedError(f"Argument {spec.get('name') or index + 1} must be at least {minimum}.")
            if maximum is not None and value > maximum:
                raise SmartThingsUnsupportedError(f"Argument {spec.get('name') or index + 1} must be at most {maximum}.")


async def refresh_device_status(device: Device) -> None:
    try:
        await send_command(device, "refresh", "refresh")
        await asyncio.sleep(1.5)
    except SmartThingsServiceError:
        logger.info("SmartThings refresh command failed for device #%s.", device.id, exc_info=True)


async def get_status(device: Device, *, refresh_first: bool = False) -> dict[str, Any]:
    if refresh_first:
        await refresh_device_status(device)
    payload = await request(await token_from_device(device), f"/devices/{_device_id(device)}/status")
    main = payload.get("components", {}).get(_component_id(device), {})
    switch = main.get("switch", {}).get("switch", {}).get("value")
    samsung_switch = main.get("samsungce.switch", {}).get("switch", {}).get("value")
    level = main.get("switchLevel", {}).get("level", {}).get("value")
    door = main.get("doorControl", {}).get("door", {}).get("value") or main.get("garageDoorControl", {}).get("door", {}).get("value")
    contact = main.get("contactSensor", {}).get("contact", {}).get("value")
    return {
        "is_on": switch == "on" or samsung_switch == "on" or door == "open" or contact == "open",
        "is_open": True if (door == "open" or contact == "open") else False if (door == "closed" or contact == "closed") else None,
        "luminance": int(level) if level is not None else None,
        "appliance": extract_appliance_summary(device, payload),
        "raw": payload,
    }


async def refresh_view_inside(device: Device, focus_area: str | None = None) -> dict[str, Any]:
    if focus_area:
        await send_command(device, "samsungce.viewInside", "refreshSpecificArea", [focus_area], component="main")
    else:
        await send_command(device, "samsungce.viewInside", "refreshAll", [], component="main")
    return await get_status(device)


async def get_view_inside_image(device: Device, file_id: str) -> tuple[bytes, str]:
    safe_file_id = urllib.parse.quote(file_id, safe="")
    safe_device_id = urllib.parse.quote(_device_id(device), safe="")
    urls = [
        f"{API_BASE}/devices/{safe_device_id}/files/{safe_file_id}",
        f"{API_BASE}/devices/{safe_device_id}/files/{safe_file_id}/download",
        f"{API_BASE}/devices/{safe_device_id}/components/main/capabilities/samsungce.viewInside/files/{safe_file_id}",
        f"{API_BASE}/devices/{safe_device_id}/components/main/capabilities/samsungce.viewInside/contents/{safe_file_id}",
    ]
    return await request_bytes(await token_from_device(device), urls)


def _value(component: dict[str, Any], capability: str, attribute: str) -> Any:
    return component.get(capability, {}).get(attribute, {}).get("value")


def _compact(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("_", " ").strip()
    return value


def _has_text(device: Device, *needles: str) -> bool:
    haystack = " ".join(
        str(part or "")
        for part in (device.name, device.model, device.device_type)
    ).lower()
    return any(needle in haystack for needle in needles)


def _remove_empty(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None and value != ""}


def _extract_laundry(device: Device, payload: dict[str, Any]) -> dict[str, Any]:
    main = payload.get("components", {}).get("main", {})
    return _remove_empty({
        "type": "laundry",
        "title": "Laundry",
        "operatingState": _compact(_value(main, "samsungce.washerOperatingState", "operatingState")),
        "machineState": _compact(_value(main, "washerOperatingState", "machineState")),
        "jobState": _compact(_value(main, "washerOperatingState", "washerJobState") or _value(main, "samsungce.washerOperatingState", "washerJobState")),
        "jobPhase": _compact(_value(main, "samsungce.washerOperatingState", "washerJobPhase")),
        "remainingTime": _value(main, "samsungce.washerOperatingState", "remainingTimeStr"),
        "completionTime": _value(main, "washerOperatingState", "completionTime"),
        "cycleType": _compact(_value(main, "samsungce.washerCycle", "cycleType")),
        "waterTemperature": _compact(_value(main, "custom.washerWaterTemperature", "washerWaterTemperature")),
        "spinLevel": _compact(_value(main, "custom.washerSpinLevel", "washerSpinLevel")),
        "soilLevel": _compact(_value(main, "custom.washerSoilLevel", "washerSoilLevel")),
        "dryLevel": _compact(_value(main, "custom.dryerDryLevel", "dryerDryLevel")),
        "dryingTemperature": _compact(_value(main, "samsungce.dryerDryingTemperature", "dryingTemperature")),
        "detergent": _compact(_value(main, "samsungce.autoDispenseDetergent", "remainingAmount")),
        "softener": _compact(_value(main, "samsungce.autoDispenseSoftener", "remainingAmount")),
        "remoteControl": _compact(_value(main, "remoteControlStatus", "remoteControlEnabled")),
    })


def _extract_refrigerator(device: Device, payload: dict[str, Any]) -> dict[str, Any]:
    components = payload.get("components", {})
    main = components.get("main", {})
    cooler = components.get("cooler", {})
    freezer = components.get("freezer", {})
    icemaker = components.get("icemaker", {})
    return _remove_empty({
        "type": "refrigerator",
        "title": "Refrigerator",
        "coolerTemp": _value(cooler, "temperatureMeasurement", "temperature"),
        "coolerSetpoint": _value(cooler, "thermostatCoolingSetpoint", "coolingSetpoint"),
        "coolerDoor": _compact(_value(cooler, "contactSensor", "contact")),
        "freezerTemp": _value(freezer, "temperatureMeasurement", "temperature"),
        "freezerSetpoint": _value(freezer, "thermostatCoolingSetpoint", "coolingSetpoint"),
        "freezerDoor": _compact(_value(freezer, "contactSensor", "contact")),
        "iceMaker": _compact(_value(icemaker, "switch", "switch")),
        "waterFilterStatus": _compact(_value(main, "custom.waterFilter", "waterFilterStatus")),
        "waterFilterUsage": _value(main, "custom.waterFilter", "waterFilterUsage"),
        "rapidCooling": _compact(_value(main, "refrigeration", "rapidCooling")),
        "rapidFreezing": _compact(_value(main, "refrigeration", "rapidFreezing")),
        "powerCool": _value(main, "samsungce.powerCool", "activated"),
        "powerFreeze": _value(main, "samsungce.powerFreeze", "activated"),
    })


def _extract_oven_or_microwave(device: Device, payload: dict[str, Any]) -> dict[str, Any]:
    main = payload.get("components", {}).get("main", {})
    is_microwave = _has_text(device, "microwave")
    return _remove_empty({
        "type": "microwave" if is_microwave else "oven",
        "title": "Microwave" if is_microwave else "Oven / Range",
        "operatingState": _compact(
            _value(main, "ovenOperatingState", "machineState")
            or _value(main, "microwaveOperatingState", "machineState")
            or _value(main, "samsungce.ovenOperatingState", "operatingState")
        ),
        "jobState": _compact(
            _value(main, "ovenOperatingState", "ovenJobState")
            or _value(main, "microwaveOperatingState", "microwaveJobState")
            or _value(main, "samsungce.ovenOperatingState", "ovenJobState")
        ),
        "mode": _compact(
            _value(main, "ovenMode", "ovenMode")
            or _value(main, "microwaveMode", "microwaveMode")
            or _value(main, "samsungce.ovenMode", "ovenMode")
        ),
        "door": _compact(_value(main, "samsungce.doorState", "doorState")),
        "cavity": _compact(_value(main, "custom.ovenCavityStatus", "ovenCavityStatus")),
        "power": _compact(_value(main, "samsungce.microwavePower", "power")),
        "lamp": _compact(_value(main, "samsungce.lamp", "switch")),
        "hoodFan": _compact(_value(main, "samsungce.hoodFanSpeed", "fanSpeed")),
        "setpoint": _value(main, "ovenSetpoint", "ovenSetpoint") or _value(main, "samsungce.ovenSetpoint", "ovenSetpoint"),
        "temperature": _value(main, "temperatureMeasurement", "temperature"),
        "completionTime": _value(main, "ovenOperatingState", "completionTime") or _value(main, "microwaveOperatingState", "completionTime"),
        "switch": _compact(_value(main, "switch", "switch") or _value(main, "samsungce.switch", "switch")),
    })


def extract_appliance_summary(device: Device, payload: dict[str, Any]) -> dict[str, Any] | None:
    if _has_text(device, "washer", "dryer", "laundry"):
        return _extract_laundry(device, payload)
    if _has_text(device, "refrigerator", "fridge", "freezer"):
        return _extract_refrigerator(device, payload)
    if _has_text(device, "microwave", "oven", "range", "stove"):
        return _extract_oven_or_microwave(device, payload)
    return None


async def send_command(
    device: Device,
    capability: str,
    command: str,
    arguments: Optional[list[Any]] = None,
    component: str = "main",
) -> dict[str, Any]:
    body = {
        "commands": [
            {
                "component": component,
                "capability": capability,
                "command": command,
                "arguments": arguments or [],
            }
        ]
    }
    return await request(await token_from_device(device), f"/devices/{_device_id(device)}/commands", method="POST", body=body)


async def execute_validated_command(device: Device, component: str, capability: str, command: str, arguments: list[Any]) -> dict[str, Any]:
    await validate_command(device, component, capability, command, arguments)
    return await send_command(device, capability, command, arguments, component=component)


async def turn_on(device: Device) -> dict[str, Any]:
    await send_command(device, "switch", "on")
    return {"is_on": True, "raw": {}}


async def turn_off(device: Device) -> dict[str, Any]:
    await send_command(device, "switch", "off")
    return {"is_on": False, "raw": {}}


async def toggle(device: Device) -> dict[str, Any]:
    current = await get_status(device)
    return await turn_off(device) if current["is_on"] else await turn_on(device)


async def set_brightness(device: Device, luminance: int) -> dict[str, Any]:
    await send_command(device, "switchLevel", "setLevel", [luminance])
    return {"is_on": True, "luminance": luminance, "raw": {}}
