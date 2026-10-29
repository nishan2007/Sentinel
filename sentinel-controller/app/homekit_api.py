from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app import db, homekit_db, homekit_service


router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parent / "static"


class HomeKitSettingsUpdate(BaseModel):
    enabled: bool | None = None
    bridge_name: str | None = Field(default=None, min_length=1, max_length=64)
    port: int | None = Field(default=None, ge=1024, le=65535)


class HomeKitAccessoryUpdate(BaseModel):
    enabled: bool | None = None
    profile: str | None = Field(default=None, max_length=40)


@router.get("/homekit", include_in_schema=False)
async def homekit_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "homekit.html")


@router.get("/api/homekit/status")
async def get_homekit_status() -> dict:
    return await homekit_service.status()


@router.get("/api/homekit/pairing-qr", include_in_schema=False)
async def get_homekit_pairing_qr() -> Response:
    details = homekit_service.pairing_details()
    if not details["setup_uri"]:
        raise HTTPException(status_code=404, detail="The bridge is paired or is not running.")
    import io
    import pyqrcode
    output = io.BytesIO()
    pyqrcode.create(details["setup_uri"]).svg(output, scale=6, quiet_zone=2)
    return Response(output.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.put("/api/homekit/settings")
async def put_homekit_settings(payload: HomeKitSettingsUpdate) -> dict:
    before = await homekit_db.get_settings()
    settings = await homekit_db.update_settings(payload.model_dump(exclude_unset=True))
    if settings != before:
        await homekit_service.restart()
    return await homekit_service.status()


@router.get("/api/homekit/accessories")
async def get_homekit_accessories() -> list[dict]:
    rows = await homekit_service.sync_accessory_rows()
    devices = {device.id: device for device in await db.list_devices()}
    result = []
    for row in rows:
        device = devices.get(row["device_id"])
        if not device:
            continue
        detected_profile, unsupported_reason = homekit_service.classify(device)
        result.append({
            **row,
            "enabled": bool(row["enabled"]),
            "device_enabled": bool(row["device_enabled"]),
            "detected_profile": detected_profile,
            "supported": detected_profile is not None,
            "unsupported_reason": unsupported_reason,
        })
    return result


@router.put("/api/homekit/accessories/{device_id}")
async def put_homekit_accessory(device_id: int, payload: HomeKitAccessoryUpdate) -> dict:
    device = await db.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found.")
    profile, reason = homekit_service.classify(device)
    requested_profile = payload.profile or profile
    if not requested_profile:
        raise HTTPException(status_code=422, detail=reason or "Unsupported device.")
    await homekit_db.ensure_accessory(device_id, requested_profile)
    updated = await homekit_db.update_accessory(
        device_id,
        enabled=payload.enabled,
        profile=payload.profile,
    )
    await homekit_service.restart()
    return updated or {}


@router.post("/api/homekit/restart")
async def restart_homekit() -> dict:
    await homekit_service.restart()
    return await homekit_service.status()


@router.post("/api/homekit/reset-pairing")
async def reset_homekit_pairing() -> dict:
    await homekit_service.reset_pairing()
    return await homekit_service.status()
