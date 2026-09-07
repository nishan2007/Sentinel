import time
from typing import Any

from app import db, smartthings_service
from app.schemas import (
    DeviceCreate,
    DeviceUpdate,
    SmartThingsImportedDevice,
    SmartThingsImportRequest,
    SmartThingsImportResponse,
)
from app.source_registry import find_overlaps, native_source_from_text


CONTROL_CAPABILITIES = {
    "switch",
    "switchLevel",
    "doorControl",
    "garageDoorControl",
    "washerOperatingState",
    "dryerOperatingState",
    "ovenOperatingState",
    "microwaveOperatingState",
    "samsungce.ovenOperatingState",
    "samsungce.ovenMode",
    "samsungce.ovenSetpoint",
    "samsungce.doorState",
    "samsungce.microwavePower",
    "samsungce.lamp",
    "samsungce.hoodFanSpeed",
    "custom.ovenCavityStatus",
    "ovenMode",
    "ovenSetpoint",
    "temperatureMeasurement",
    "thermostatCoolingSetpoint",
    "contactSensor",
    "refrigeration",
}


def capabilities_for(device: dict[str, Any]) -> list[str]:
    caps: set[str] = set()
    for component in device.get("components", []):
        for capability in component.get("capabilities", []):
            cap_id = capability.get("id")
            if cap_id:
                caps.add(cap_id)
    return sorted(caps)


def control_capability_summary(caps: list[str]) -> str:
    relevant = [cap for cap in caps if cap in CONTROL_CAPABILITIES]
    return ",".join(relevant or caps[:8])


def device_name(device: dict[str, Any]) -> str:
    return device.get("label") or device.get("name") or device.get("deviceId") or "SmartThings Device"


def manufacturer(device: dict[str, Any]) -> str:
    parts = [
        device.get("manufacturerName"),
        device.get("presentationId"),
        device.get("vid"),
    ]
    return " ".join(part for part in parts if part).lower()


def is_likely_meross_mirror(device: dict[str, Any], caps: list[str]) -> bool:
    descriptor = " ".join(
        str(part or "")
        for part in (
            device.get("manufacturerName"),
            device.get("presentationId"),
            device.get("vid"),
            device.get("deviceTypeName"),
            device.get("type"),
            device.get("mnmn"),
            device.get("model"),
            device.get("ocf", {}).get("modelNumber") if isinstance(device.get("ocf"), dict) else None,
        )
    ).lower()
    return "viper" in descriptor and "switch" in caps


def overlap_reason(device: dict[str, Any], existing) -> str | None:
    device_id = device.get("deviceId")
    name = device_name(device)
    caps = capabilities_for(device)
    native_source = native_source_from_text(
        manufacturer(device),
        device.get("deviceTypeName"),
        device.get("type"),
        name,
    )
    if is_likely_meross_mirror(device, caps):
        return "SmartThings VIPER switch appears to mirror a native Meross switch; use the native Meross source"
    overlaps = find_overlaps(
        existing,
        source="smartthings",
        name=name,
        external_id=device_id,
        host=f"smartthings:{device_id}" if device_id else None,
    )
    if overlaps:
        winner = overlaps[0].device
        return f"matches existing {winner.brand} device '{winner.name}'"
    if native_source == "meross":
        return "SmartThings copy appears to be a Meross device; use the native Meross source"
    if native_source in {"ring", "yale"}:
        return f"SmartThings copy appears to be a {native_source.title()} device; import from the native source when available"
    return None


async def import_from_smartthings(payload: SmartThingsImportRequest) -> SmartThingsImportResponse:
    credentials = await _credentials(payload)
    token = await smartthings_service.access_token(credentials) if credentials.get("refresh_token") else credentials["access_token"]
    device_key = (
        smartthings_service.credentials_to_device_key(credentials, credentials)
        if credentials.get("refresh_token")
        else token
    )
    smartthings_devices = await smartthings_service.list_devices(token)
    existing = await db.list_devices()

    imported: list[SmartThingsImportedDevice] = []
    skipped: list[SmartThingsImportedDevice] = []

    for raw_device in smartthings_devices:
        caps = capabilities_for(raw_device)
        if not CONTROL_CAPABILITIES.intersection(caps):
            continue

        name = device_name(raw_device)
        device_id = raw_device["deviceId"]
        host = f"smartthings:{device_id}"
        existing_smartthings = next(
            (
                device
                for device in existing
                if device.brand.lower() == "smartthings"
                and (device.device_uuid == device_id or device.host == host)
            ),
            None,
        )
        reason = overlap_reason(raw_device, existing) if payload.exclude_overlaps else None
        record = SmartThingsImportedDevice(
            name=name,
            device_uuid=device_id,
            device_type=control_capability_summary(caps),
            model=raw_device.get("deviceTypeName") or raw_device.get("type"),
            capabilities=caps,
            saved=False,
            skipped=bool(reason),
            skip_reason=reason,
        )

        if reason:
            if payload.save_devices and existing_smartthings:
                updated = await db.update_device(
                    existing_smartthings.id,
                    DeviceUpdate(
                        model=raw_device.get("deviceTypeName") or raw_device.get("type"),
                        host=host,
                        device_key=device_key,
                        device_uuid=device_id,
                        device_type=control_capability_summary(caps),
                    ),
                )
                if updated:
                    record.id = updated.id
                    record.saved = True
            skipped.append(record)
            continue

        if payload.save_devices:
            saved = await db.upsert_imported_device(
                DeviceCreate(
                    name=name,
                    brand="smartthings",
                    model=raw_device.get("deviceTypeName") or raw_device.get("type"),
                    host=host,
                    device_key=device_key,
                    device_uuid=device_id,
                    device_type=control_capability_summary(caps),
                    channel=0,
                    is_enabled=True,
                )
            )
            record.id = saved.id
            record.saved = True

        imported.append(record)

    return SmartThingsImportResponse(
        imported=imported,
        skipped=skipped,
        note="SmartThings credentials are stored only on imported SmartThings device records so Sentinel can refresh OAuth tokens and control devices through the SmartThings API.",
    )


async def _credentials(payload: SmartThingsImportRequest) -> dict[str, Any]:
    base = {
        "client_id": payload.client_id,
        "client_secret": payload.client_secret.get_secret_value() if payload.client_secret else None,
        "refresh_token": payload.refresh_token.get_secret_value() if payload.refresh_token else None,
        "access_token": payload.access_token.get_secret_value() if payload.access_token else None,
    }
    if payload.authorization_code:
        if not base["client_id"] or not base["client_secret"]:
            raise smartthings_service.MissingSmartThingsTokenError("SmartThings authorization code exchange needs client_id and client_secret.")
        token_payload = await smartthings_service.exchange_authorization_code(
            client_id=base["client_id"],
            client_secret=base["client_secret"],
            authorization_code=payload.authorization_code.get_secret_value(),
            redirect_uri=payload.redirect_uri,
        )
        return {
            **base,
            "refresh_token": token_payload.get("refresh_token") or base.get("refresh_token"),
            "access_token": token_payload.get("access_token"),
            "expires_at": int(time.time()) + int(token_payload.get("expires_in") or 86400),
        }
    if base.get("refresh_token"):
        return {key: value for key, value in base.items() if value}
    if base.get("access_token"):
        return {key: value for key, value in base.items() if value}
    if payload.token:
        return {"access_token": payload.token.get_secret_value()}
    raise smartthings_service.MissingSmartThingsTokenError("Provide SmartThings OAuth credentials or a short-lived personal access token.")
