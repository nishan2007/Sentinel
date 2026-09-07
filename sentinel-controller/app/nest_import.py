from typing import Any

from app import db, nest_service
from app.schemas import DeviceCreate, NestImportedDevice, NestImportRequest, NestImportResponse
from app.source_registry import disable_lower_priority_overlaps, find_overlaps


async def import_from_nest(payload: NestImportRequest) -> NestImportResponse:
    credentials = await _credentials(payload)
    raw_devices = await nest_service.list_devices(credentials)
    existing = await db.list_devices()

    imported: list[NestImportedDevice] = []
    skipped: list[NestImportedDevice] = []

    for raw_device in raw_devices:
        if not nest_service.is_thermostat(raw_device):
            continue

        name = nest_service.display_name(raw_device)
        device_uuid = raw_device["name"]
        host = f"nest:{device_uuid}"
        overlaps = find_overlaps(
            existing,
            source="nest",
            name=name,
            external_id=device_uuid,
            host=host,
        ) if payload.exclude_overlaps else []
        same_source_overlap = next((item for item in overlaps if item.device.brand.lower() == "nest"), None)
        reason = f"already imported as Nest thermostat #{same_source_overlap.device.id}" if same_source_overlap else None

        record = NestImportedDevice(
            name=name,
            device_uuid=device_uuid,
            device_type="thermostat",
            model=raw_device.get("type"),
            room=nest_service.room_name(raw_device),
            saved=False,
            skipped=bool(reason),
            skip_reason=reason,
        )

        if reason:
            skipped.append(record)
            continue

        if payload.save_devices:
            disabled = await disable_lower_priority_overlaps(
                source="nest",
                name=name,
                external_id=device_uuid,
                host=host,
            ) if payload.exclude_overlaps else []
            saved = await db.upsert_imported_device(
                DeviceCreate(
                    name=name,
                    brand="nest",
                    model=raw_device.get("type"),
                    host=host,
                    device_key=nest_service.credentials_to_device_key(payload.project_id, credentials, credentials),
                    device_uuid=device_uuid,
                    device_type="thermostat",
                    channel=0,
                    is_enabled=True,
                )
            )
            record.id = saved.id
            record.saved = True
            record.disabled_overlaps = [item.device.name for item in disabled]

        imported.append(record)

    return NestImportResponse(
        imported=imported,
        skipped=skipped,
        note="Nest thermostats are imported from Google Nest Device Access / Smart Device Management API. Tokens are stored on Nest device records for source-level thermostat control.",
    )


async def _credentials(payload: NestImportRequest) -> dict[str, Any]:
    base = {
        "project_id": payload.project_id,
        "client_id": payload.client_id,
        "client_secret": payload.client_secret.get_secret_value() if payload.client_secret else None,
        "refresh_token": payload.refresh_token.get_secret_value() if payload.refresh_token else None,
        "access_token": payload.access_token.get_secret_value() if payload.access_token else None,
    }
    if payload.authorization_code:
        if not base["client_id"] or not base["client_secret"]:
            raise nest_service.MissingNestCredentialsError("Nest authorization code exchange needs client_id and client_secret.")
        token_payload = await nest_service.exchange_authorization_code(
            client_id=base["client_id"],
            client_secret=base["client_secret"],
            authorization_code=payload.authorization_code.get_secret_value(),
            redirect_uri=payload.redirect_uri,
        )
        return {
            **base,
            "refresh_token": token_payload.get("refresh_token") or base.get("refresh_token"),
            "access_token": token_payload.get("access_token"),
            "expires_at": token_payload.get("expires_in"),
        }
    if base.get("access_token") or base.get("refresh_token"):
        return {key: value for key, value in base.items() if value}
    raise nest_service.MissingNestCredentialsError("Provide a Nest authorization_code, refresh_token, or access_token.")
