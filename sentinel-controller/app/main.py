import asyncio
from datetime import datetime, timezone
import json
import logging
import re
import secrets
import subprocess
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import (
    camera_db,
    camera_service,
    cloud_import,
    cudy_service,
    db,
    discovery,
    meross_service,
    nest_import,
    nest_service,
    printer_service,
    ring_import,
    ring_service,
    smartthings_import,
    smartthings_service,
    yale_import,
    yale_service,
)
from app.schemas import (
    BrightnessRequest,
    CudyRebootRequest,
    CameraCreateRequest,
    CameraDiscoveryRequest,
    CameraOnvifProfilesRequest,
    CameraOut,
    CameraStorageUpdate,
    CameraUpdateRequest,
    DeviceActionResult,
    DeviceCreate,
    DeviceOut,
    DeviceState,
    DeviceUpdate,
    HealthResponse,
    MerossCloudImportRequest,
    MerossCloudImportResponse,
    NestCommandRequest,
    NestImportRequest,
    NestImportResponse,
    NetworkScanRequest,
    NetworkScanResult,
    PrinterDiscoveryRequest,
    PrinterInkRefillRequest,
    RingAlertResponse,
    RingImportRequest,
    RingImportResponse,
    RingWebRtcCandidateRequest,
    RingWebRtcOfferRequest,
    SmartThingsImportRequest,
    SmartThingsImportResponse,
    SmartThingsCommandRequest,
    SmartThingsOAuthStartRequest,
    SmartThingsOAuthStartResponse,
    DuplicateRepairResponse,
    ReliabilityHealthResponse,
    YaleImportRequest,
    YaleImportResponse,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
ICONS_DIR = APP_DIR.parent.parent / "icons"
BRAND_DIR = APP_DIR.parent.parent / "brand"
RING_SNAPSHOT_DIR = APP_DIR.parent / "data" / "ring_snapshots"
SMARTTHINGS_OAUTH_DIR = APP_DIR.parent / "data" / "smartthings_oauth"
BACKGROUND_REFRESH_SECONDS = 300
BACKGROUND_DEVICE_PAUSE_SECONDS = 5
BACKGROUND_PRINTER_REFRESH_SECONDS = 300

reliability_state = {
    "started_at": None,
    "last_cloud_refresh_started_at": None,
    "last_cloud_refresh_finished_at": None,
    "last_cloud_refresh_error": None,
    "cloud_refresh_count": 0,
    "cloud_refresh_running": False,
    "credential_checks": {},
}
background_refresh_task: asyncio.Task | None = None
background_printer_refresh_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_refresh_task, background_printer_refresh_task
    await db.init_db()
    await camera_db.init_camera_db()
    await camera_service.start_manager()
    logger.info("Database initialized at %s", db.resolve_database_path())
    reliability_state["started_at"] = _now_iso()
    background_refresh_task = asyncio.create_task(_background_cloud_refresh_loop())
    background_printer_refresh_task = asyncio.create_task(_background_printer_refresh_loop())
    yield
    if background_refresh_task:
        background_refresh_task.cancel()
        try:
            await background_refresh_task
        except asyncio.CancelledError:
            pass
    if background_printer_refresh_task:
        background_printer_refresh_task.cancel()
        try:
            await background_printer_refresh_task
        except asyncio.CancelledError:
            pass
    await ring_service.close_cached_clients()
    await camera_service.stop_manager()


app = FastAPI(
    title="Sentinel",
    description="Local REST controller for Sentinel smart-home devices and integrations.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")
app.mount("/brand", StaticFiles(directory=BRAND_DIR), name="brand")


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.post("/", include_in_schema=False)
async def root_smartthings_ping(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    lifecycle = str(payload.get("lifecycle") or "").upper()
    confirmation_data = payload.get("confirmationData") if isinstance(payload.get("confirmationData"), dict) else {}
    confirmation_url = (
        confirmation_data.get("confirmationUrl")
        or confirmation_data.get("confirmation_url")
        or payload.get("confirmationUrl")
        or payload.get("confirmation_url")
    )
    if lifecycle == "CONFIRMATION" and confirmation_url:
        try:
            req = urllib.request.Request(
                confirmation_url,
                headers={"Accept": "application/json", "User-Agent": "Sentinel/0.1"},
            )
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
            logger.info("Confirmed SmartThings SmartApp target URL.")
            return {"status": "ok", "service": "sentinel", "lifecycle": "CONFIRMATION", "confirmed": True}
        except Exception as exc:
            logger.exception("SmartThings confirmation URL request failed.")
            return {
                "status": "error",
                "service": "sentinel",
                "lifecycle": "CONFIRMATION",
                "confirmed": False,
                "message": str(exc),
            }
    logger.info("SmartThings target URL ping lifecycle=%s keys=%s", lifecycle or "unknown", sorted(payload.keys()))
    return {"status": "ok", "service": "sentinel", "lifecycle": lifecycle or None}


@app.get("/dashboard", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/cameras", include_in_schema=False)
async def cameras_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "cameras.html")


def _device_out(device) -> DeviceOut:
    return DeviceOut.model_validate(device)


async def _load_device_or_404(device_id: int):
    device = await db.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    return device


def _raise_meross_error(exc: meross_service.MerossServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_smartthings_error(exc: smartthings_service.SmartThingsServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_ring_error(exc: ring_service.RingServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_yale_error(exc: yale_service.YaleServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_cudy_error(exc: cudy_service.CudyServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _raise_nest_error(exc: nest_service.NestServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _is_smartthings(device) -> bool:
    return device.brand.lower() == "smartthings"


def _is_nest(device) -> bool:
    return device.brand.lower() == "nest"


def _is_ring(device) -> bool:
    return device.brand.lower() == "ring"


def _is_ip_camera(device) -> bool:
    return device.brand.lower() == "ip-camera"


def _ring_snapshot_path(device_id: int) -> Path:
    return RING_SNAPSHOT_DIR / f"{device_id}.jpg"


async def _refresh_ring_snapshot_cache(device) -> None:
    body = await ring_service.get_snapshot(device)
    RING_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = _ring_snapshot_path(device.id)
    temp_path = snapshot_path.with_suffix(".jpg.tmp")
    await asyncio.to_thread(temp_path.write_bytes, body)
    await asyncio.to_thread(temp_path.replace, snapshot_path)


def _is_yale(device) -> bool:
    return device.brand.lower() == "yale"


def _is_cudy(device) -> bool:
    return device.brand.lower() == "cudy"


def _is_printer(device) -> bool:
    return device.brand.lower() == "printer"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_cloud_device(device) -> bool:
    return device.brand.lower() in {"smartthings", "nest", "ring", "yale"}


def _device_health_row(device, *, status: str, message: str = "", checked_at: str | None = None) -> dict:
    return {
        "id": device.id,
        "name": device.name,
        "brand": device.brand,
        "model": device.model,
        "status": status,
        "message": message,
        "checked_at": checked_at or _now_iso(),
    }


def _last_state_summary(state: dict) -> str:
    return json.dumps({"is_on": state.get("is_on"), "appliance": state.get("appliance"), "raw": state.get("raw")})


def _cached_state(device) -> dict | None:
    if not device.last_state:
        return None
    try:
        return json.loads(device.last_state)
    except json.JSONDecodeError:
        return None


async def _persist_smartthings_oauth_credentials(device) -> None:
    credentials = smartthings_service.updated_credentials_for_device(device.id)
    if not credentials or not credentials.get("client_id"):
        return

    device_key = json.dumps(credentials)
    updated = 0
    for candidate in await db.list_devices():
        if candidate.brand.lower() != "smartthings" or not candidate.device_key:
            continue
        try:
            candidate_credentials = smartthings_service.credentials_from_secret(candidate.device_key)
        except smartthings_service.SmartThingsServiceError:
            continue
        if candidate_credentials.get("client_id") != credentials.get("client_id"):
            continue
        await db.update_device(candidate.id, DeviceUpdate(device_key=device_key))
        updated += 1
    if updated:
        logger.info("Persisted rotated SmartThings OAuth credentials to %s device row(s).", updated)


async def _get_cloud_state(device) -> dict:
    if _is_smartthings(device):
        state = await smartthings_service.get_status(device)
        await _persist_smartthings_oauth_credentials(device)
        return state
    if _is_nest(device):
        return await nest_service.get_status(device)
    if _is_ring(device):
        return await ring_service.get_status(device)
    if _is_yale(device):
        return await yale_service.get_status(device)
    raise ValueError(f"{device.brand} is not a cloud device.")


async def _refresh_cloud_device(device) -> dict:
    state = await _get_cloud_state(device)
    await db.save_last_state(device.id, _last_state_summary(state))
    row = _device_health_row(device, status="ok")
    reliability_state["credential_checks"][device.id] = row
    return row


async def _refresh_cloud_devices_once() -> list[dict]:
    reliability_state["cloud_refresh_running"] = True
    reliability_state["last_cloud_refresh_started_at"] = _now_iso()
    reliability_state["last_cloud_refresh_error"] = None
    results: list[dict] = []
    try:
        devices = [device for device in await db.list_devices() if device.is_enabled and _is_cloud_device(device)]
        for index, device in enumerate(devices):
            try:
                results.append(await _refresh_cloud_device(device))
            except Exception as exc:
                logger.info("Cloud refresh failed for %s #%s.", device.brand, device.id, exc_info=True)
                row = _device_health_row(device, status="error", message=str(exc))
                reliability_state["credential_checks"][device.id] = row
                results.append(row)
            if index < len(devices) - 1:
                await asyncio.sleep(BACKGROUND_DEVICE_PAUSE_SECONDS)
        reliability_state["cloud_refresh_count"] = int(reliability_state["cloud_refresh_count"]) + 1
        return results
    except Exception as exc:
        reliability_state["last_cloud_refresh_error"] = str(exc)
        raise
    finally:
        reliability_state["last_cloud_refresh_finished_at"] = _now_iso()
        reliability_state["cloud_refresh_running"] = False


async def _background_cloud_refresh_loop() -> None:
    while True:
        try:
            await _refresh_cloud_devices_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("Background cloud refresh failed.", exc_info=True)
        await asyncio.sleep(BACKGROUND_REFRESH_SECONDS)


async def _refresh_printer_device(device) -> None:
    checked_at = _now_iso()
    state = await printer_service.get_status(device, checked_at=checked_at)
    await db.save_last_state(device.id, _last_state_summary(state))


async def _refresh_printer_devices_once() -> None:
    devices = [device for device in await db.list_devices() if device.is_enabled and _is_printer(device)]
    for index, device in enumerate(devices):
        try:
            await _refresh_printer_device(device)
        except printer_service.PrinterTimeoutError as exc:
            checked_at = _now_iso()
            state = printer_service.offline_status(device, _cached_state(device), exc.message, checked_at=checked_at)
            await db.save_last_state(device.id, _last_state_summary(state))
            logger.info("Background printer refresh timed out for device #%s: %s", device.id, exc.message)
        except printer_service.PrinterServiceError as exc:
            checked_at = _now_iso()
            state = printer_service.offline_status(device, _cached_state(device), exc.message, checked_at=checked_at)
            await db.save_last_state(device.id, _last_state_summary(state))
            logger.info("Background printer refresh failed for device #%s: %s", device.id, exc.message)
        except Exception:
            logger.info("Background printer refresh failed for device #%s.", device.id, exc_info=True)
        if index < len(devices) - 1:
            await asyncio.sleep(BACKGROUND_DEVICE_PAUSE_SECONDS)


async def _background_printer_refresh_loop() -> None:
    while True:
        try:
            await _refresh_printer_devices_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.info("Background printer refresh failed.", exc_info=True)
        await asyncio.sleep(BACKGROUND_PRINTER_REFRESH_SECONDS)


def _is_likely_smartthings_mirror(device) -> bool:
    text = " ".join(str(part or "") for part in (device.name, device.model, device.device_type, device.brand)).lower()
    if device.brand.lower() != "smartthings":
        return False
    if "viper" in text and "switch" in text:
        return True
    return False


async def _duplicate_candidates() -> list[dict]:
    devices = await db.list_devices()
    candidates = []
    for device in devices:
        if not device.is_enabled or not _is_likely_smartthings_mirror(device):
            continue
        candidates.append({
            "id": device.id,
            "name": device.name,
            "brand": device.brand,
            "model": device.model,
            "reason": "SmartThings VIPER switch appears to mirror a native switch.",
        })
    return candidates


def _normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.lower().split(":")
    if len(parts) == 6 and all(1 <= len(part) <= 2 for part in parts):
        return ":".join(part.zfill(2) for part in parts)

    compact = "".join(ch for ch in value.lower() if ch.isalnum())
    if len(compact) == 12:
        return ":".join(compact[index:index + 2] for index in range(0, 12, 2))
    return value.lower()


def _smartthings_oauth_state_path(state: str) -> Path:
    safe_state = re.sub(r"[^A-Za-z0-9_-]", "", state)
    return SMARTTHINGS_OAUTH_DIR / f"{safe_state}.json"


async def _save_smartthings_oauth_state(state: str, payload: SmartThingsOAuthStartRequest) -> None:
    SMARTTHINGS_OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    state_path = _smartthings_oauth_state_path(state)
    data = {
        "client_id": payload.client_id,
        "client_secret": payload.client_secret.get_secret_value(),
        "redirect_uri": payload.redirect_uri,
        "scopes": payload.scopes,
        "save_devices": payload.save_devices,
        "exclude_overlaps": payload.exclude_overlaps,
    }
    await asyncio.to_thread(state_path.write_text, json.dumps(data), "utf-8")
    await asyncio.to_thread(state_path.chmod, 0o600)


async def _load_smartthings_oauth_state(state: str) -> dict:
    state_path = _smartthings_oauth_state_path(state)
    if not state_path.exists():
        raise smartthings_service.MissingSmartThingsTokenError("SmartThings sign-in session expired. Start SmartThings sign-in from Sentinel again.")
    raw = await asyncio.to_thread(state_path.read_text, "utf-8")
    await asyncio.to_thread(state_path.unlink)
    return json.loads(raw)


def _mac_from_meross_uuid(device_uuid: str | None) -> str | None:
    if not device_uuid:
        return None
    compact = "".join(ch for ch in device_uuid.lower() if ch.isalnum())
    if len(compact) < 12:
        return None
    return _normalize_mac(compact[-12:])


def _arp_ip_by_mac_sync(mac_address: str | None) -> str | None:
    normalized = _normalize_mac(mac_address)
    if not normalized:
        return None

    try:
        output = subprocess.check_output(["arp", "-an"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None

    for line in output.splitlines():
        match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+)", line.lower())
        if match and _normalize_mac(match.group(2)) == normalized:
            return match.group(1)
    return None


async def _find_meross_host_by_uuid(device) -> str | None:
    mac_address = _mac_from_meross_uuid(device.device_uuid)
    host = await asyncio.to_thread(_arp_ip_by_mac_sync, mac_address)
    if host:
        return host

    try:
        await discovery.scan_network(port=80)
    except Exception:
        logger.info("Meross host repair scan failed.", exc_info=True)
    return await asyncio.to_thread(_arp_ip_by_mac_sync, mac_address)


async def _run_meross_with_host_repair(device, operation):
    try:
        return await operation(device), device
    except (meross_service.DeviceTimeoutError, meross_service.DeviceUnreachableError):
        replacement_host = await _find_meross_host_by_uuid(device)
        if not replacement_host or replacement_host == device.host:
            raise

        repaired_device = replace(device, host=replacement_host)
        try:
            result = await operation(repaired_device)
        except meross_service.MerossServiceError:
            raise

        await db.update_device(device.id, DeviceUpdate(host=replacement_host))
        logger.info(
            "Updated Meross host for device %s from %s to %s after signed retry.",
            device.id,
            device.host,
            replacement_host,
        )
        return result, repaired_device


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", database=str(db.resolve_database_path()))


@app.get("/reliability/health", response_model=ReliabilityHealthResponse)
async def reliability_health() -> ReliabilityHealthResponse:
    credential_rows = sorted(
        reliability_state["credential_checks"].values(),
        key=lambda row: (row.get("brand") or "", row.get("name") or ""),
    )
    has_credential_errors = any(row.get("status") == "error" for row in credential_rows)
    duplicate_candidates = await _duplicate_candidates()
    status = "needs_attention" if has_credential_errors or duplicate_candidates else "ok"
    return ReliabilityHealthResponse(
        status=status,
        background_refresh={
            "started_at": reliability_state["started_at"],
            "running": reliability_state["cloud_refresh_running"],
            "interval_seconds": BACKGROUND_REFRESH_SECONDS,
            "last_started_at": reliability_state["last_cloud_refresh_started_at"],
            "last_finished_at": reliability_state["last_cloud_refresh_finished_at"],
            "last_error": reliability_state["last_cloud_refresh_error"],
            "refresh_count": reliability_state["cloud_refresh_count"],
        },
        credentials=credential_rows,
        duplicate_candidates=duplicate_candidates,
    )


@app.post("/reliability/cloud-refresh", response_model=ReliabilityHealthResponse)
async def refresh_cloud_devices_now() -> ReliabilityHealthResponse:
    if reliability_state["cloud_refresh_running"]:
        raise HTTPException(status_code=409, detail="Cloud refresh is already running.")
    await _refresh_cloud_devices_once()
    return await reliability_health()


@app.post("/maintenance/repair-duplicates", response_model=DuplicateRepairResponse)
async def repair_duplicate_devices() -> DuplicateRepairResponse:
    devices = await db.list_devices()
    disabled = []
    kept = []
    for device in devices:
        if not _is_likely_smartthings_mirror(device):
            continue
        row = {
            "id": device.id,
            "name": device.name,
            "brand": device.brand,
            "model": device.model,
            "reason": "SmartThings VIPER switch appears to mirror a native switch.",
        }
        if device.is_enabled:
            await db.update_device(device.id, DeviceUpdate(is_enabled=False))
            disabled.append(row)
        else:
            kept.append(row)
    return DuplicateRepairResponse(
        disabled=disabled,
        kept=kept,
        note=f"Disabled {len(disabled)} duplicate SmartThings mirror device(s).",
    )


@app.get("/devices", response_model=list[DeviceOut])
async def list_devices() -> list[DeviceOut]:
    devices = await db.list_devices()
    return [_device_out(device) for device in devices if device.is_enabled]


@app.post("/devices", response_model=DeviceOut, status_code=201)
async def create_device(payload: DeviceCreate) -> DeviceOut:
    device = await db.create_device(payload)
    return _device_out(device)


@app.get("/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int) -> DeviceOut:
    device = await _load_device_or_404(device_id)
    return _device_out(device)


@app.put("/devices/{device_id}", response_model=DeviceOut)
async def update_device(device_id: int, payload: DeviceUpdate) -> DeviceOut:
    device = await db.update_device(device_id, payload)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    return _device_out(device)


@app.delete("/devices/{device_id}", status_code=204)
async def delete_device(device_id: int) -> None:
    deleted = await db.delete_device(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found.")


@app.get("/devices/{device_id}/state", response_model=DeviceState)
async def get_device_state(device_id: int) -> DeviceState:
    device = await _load_device_or_404(device_id)
    try:
        if _is_smartthings(device):
            state = await smartthings_service.get_status(device, refresh_first=True)
            await _persist_smartthings_oauth_credentials(device)
        elif _is_nest(device):
            state = await nest_service.get_status(device)
        elif _is_ring(device):
            state = await ring_service.get_status(device)
        elif _is_ip_camera(device):
            camera = await camera_db.get_camera_by_device(device.id, include_secrets=True)
            if not camera:
                raise camera_service.CameraServiceError("Camera profile is missing.", 404)
            camera_health = await camera_service.health()
            row = next((item for item in camera_health["cameras"] if item["id"] == camera["id"]), {})
            state = {"is_on": not bool(row.get("error")), "raw": {
                "camera_id": camera["id"], "recording": bool(row.get("recording")),
                "recording_enabled": bool(camera["recording_enabled"]), "error": row.get("error"),
            }}
        elif _is_yale(device):
            state = await yale_service.get_status(device)
        elif _is_cudy(device):
            state = await cudy_service.get_status(device)
        elif _is_printer(device):
            checked_at = _now_iso()
            try:
                state = await printer_service.get_status(device, checked_at=checked_at)
            except printer_service.PrinterServiceError as exc:
                state = printer_service.offline_status(device, _cached_state(device), exc.message, checked_at=checked_at)
        else:
            state, device = await _run_meross_with_host_repair(device, meross_service.get_state)
    except meross_service.MerossServiceError as exc:
        _raise_meross_error(exc)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)
    except nest_service.NestServiceError as exc:
        _raise_nest_error(exc)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)
    except yale_service.YaleServiceError as exc:
        _raise_yale_error(exc)
    except cudy_service.CudyServiceError as exc:
        _raise_cudy_error(exc)
    except camera_service.CameraServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # Persist offline printer responses too. This gives a newly-added printer a
    # useful first state instead of leaving its dashboard tile blank, while
    # offline_status preserves any previously cached supply snapshot.
    await db.save_last_state(device_id, _last_state_summary(state))
    return DeviceState(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        is_on=state["is_on"],
        is_open=state.get("is_open"),
        luminance=state.get("luminance"),
        appliance=state.get("appliance"),
        raw=state["raw"],
    )


@app.post("/devices/{device_id}/printer/ink-refill", response_model=DeviceState)
async def mark_printer_ink_refilled(device_id: int, payload: PrinterInkRefillRequest) -> DeviceState:
    device = await _load_device_or_404(device_id)
    if not _is_printer(device):
        raise HTTPException(status_code=422, detail="Ink refill reset is only available for printer devices.")
    color = payload.color.strip().lower()
    if color not in {"black", "cyan", "magenta", "yellow"}:
        raise HTTPException(status_code=400, detail="Choose black, cyan, magenta, or yellow.")
    settings = _printer_device_key_settings(device)
    refills = settings.get("ink_refills")
    if not isinstance(refills, dict):
        refills = {}
    refills[color] = {"refilled_at": _now_iso()}
    settings["ink_refills"] = refills
    updated = await db.update_device(device_id, DeviceUpdate(device_key=json.dumps(settings)))
    if updated is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    checked_at = _now_iso()
    try:
        state = await printer_service.get_status(updated, checked_at=checked_at)
    except printer_service.PrinterServiceError as exc:
        state = printer_service.offline_status(updated, _cached_state(updated), exc.message, checked_at=checked_at)
    await db.save_last_state(device_id, _last_state_summary(state))
    return DeviceState(
        id=updated.id,
        name=updated.name,
        host=updated.host,
        channel=updated.channel,
        is_on=state["is_on"],
        is_open=state.get("is_open"),
        luminance=state.get("luminance"),
        appliance=state.get("appliance"),
        raw=state["raw"],
    )


def _printer_device_key_settings(device) -> dict:
    if not device.device_key:
        return {"community": printer_service.DEFAULT_COMMUNITY}
    value = device.device_key.strip()
    if not value:
        return {"community": printer_service.DEFAULT_COMMUNITY}
    if not value.startswith("{"):
        return {"community": value}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"community": printer_service.DEFAULT_COMMUNITY}
    return parsed if isinstance(parsed, dict) else {"community": printer_service.DEFAULT_COMMUNITY}


@app.get("/devices/{device_id}/capabilities")
async def inspect_device_capabilities(device_id: int) -> dict:
    device = await _load_device_or_404(device_id)
    if not _is_smartthings(device):
        raise HTTPException(status_code=422, detail="Capability inspection is only available for SmartThings devices.")
    try:
        result = await smartthings_service.inspect_capabilities(device)
        await _persist_smartthings_oauth_credentials(device)
        return result
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)


async def _run_action(device_id: int, action: str) -> DeviceActionResult:
    device = await _load_device_or_404(device_id)
    meross_actions = {
        "turn-on": meross_service.turn_on,
        "turn-off": meross_service.turn_off,
        "toggle": meross_service.toggle,
        "open": meross_service.garage_open,
        "close": meross_service.garage_close,
    }
    smartthings_actions = {
        "turn-on": smartthings_service.turn_on,
        "turn-off": smartthings_service.turn_off,
        "toggle": smartthings_service.toggle,
    }
    yale_actions = {
        "lock": yale_service.lock,
        "unlock": yale_service.unlock,
    }
    requested_state = {"turn-on": True, "turn-off": False, "toggle": None, "open": True, "close": False, "lock": True, "unlock": False}[action]

    try:
        if _is_smartthings(device):
            if action not in smartthings_actions:
                raise smartthings_service.SmartThingsUnsupportedError("This SmartThings action is not supported yet.")
            result = await smartthings_actions[action](device)
        elif _is_nest(device):
            raise nest_service.NestUnsupportedError("Use the Nest thermostat endpoint for mode and setpoint control.")
        elif _is_ring(device):
            raise ring_service.RingServiceError("Ring dashboard controls are status-only for now.")
        elif _is_yale(device):
            if action not in yale_actions:
                raise yale_service.YaleServiceError("This Yale action is not supported.")
            result = await yale_actions[action](device)
        elif _is_cudy(device):
            raise cudy_service.CudyUnsupportedError("Use the Cudy router endpoints for router management.")
        else:
            if action not in meross_actions:
                raise meross_service.UnsupportedModelError("This Meross action is not supported.")
            result, device = await _run_meross_with_host_repair(device, meross_actions[action])
    except meross_service.MerossServiceError as exc:
        _raise_meross_error(exc)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)
    except nest_service.NestServiceError as exc:
        _raise_nest_error(exc)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)
    except yale_service.YaleServiceError as exc:
        _raise_yale_error(exc)
    except cudy_service.CudyServiceError as exc:
        _raise_cudy_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": result.get("is_on")}))
    return DeviceActionResult(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        requested_state=requested_state,
        is_on=result.get("is_on"),
        is_open=result.get("is_open"),
        luminance=result.get("luminance"),
        message=f"{device.name} command completed.",
    )


@app.post("/devices/{device_id}/turn-on", response_model=DeviceActionResult)
async def turn_on_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "turn-on")


@app.post("/devices/{device_id}/turn-off", response_model=DeviceActionResult)
async def turn_off_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "turn-off")


@app.post("/devices/{device_id}/toggle", response_model=DeviceActionResult)
async def toggle_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "toggle")


@app.post("/devices/{device_id}/open", response_model=DeviceActionResult)
async def open_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "open")


@app.post("/devices/{device_id}/close", response_model=DeviceActionResult)
async def close_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "close")


@app.post("/devices/{device_id}/lock", response_model=DeviceActionResult)
async def lock_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "lock")


@app.post("/devices/{device_id}/unlock", response_model=DeviceActionResult)
async def unlock_device(device_id: int) -> DeviceActionResult:
    return await _run_action(device_id, "unlock")


@app.post("/devices/{device_id}/brightness", response_model=DeviceActionResult)
async def set_device_brightness(device_id: int, payload: BrightnessRequest) -> DeviceActionResult:
    device = await _load_device_or_404(device_id)
    try:
        if _is_smartthings(device):
            result = await smartthings_service.set_brightness(device, payload.luminance)
        else:
            result, device = await _run_meross_with_host_repair(
                device,
                lambda repaired_device: meross_service.set_brightness(repaired_device, payload.luminance),
            )
    except meross_service.MerossServiceError as exc:
        _raise_meross_error(exc)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": result.get("is_on"), "luminance": result.get("luminance")}))
    return DeviceActionResult(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        requested_state=None,
        is_on=result.get("is_on"),
        luminance=result.get("luminance"),
        message=f"{device.name} brightness set to {payload.luminance}%.",
    )


@app.post("/devices/{device_id}/smartthings/command", response_model=DeviceActionResult)
async def execute_smartthings_command(device_id: int, payload: SmartThingsCommandRequest) -> DeviceActionResult:
    device = await _load_device_or_404(device_id)
    if not _is_smartthings(device):
        raise HTTPException(status_code=422, detail="SmartThings commands are only available for SmartThings devices.")
    try:
        await smartthings_service.execute_validated_command(
            device,
            payload.component,
            payload.capability,
            payload.command,
            payload.arguments,
        )
        await _persist_smartthings_oauth_credentials(device)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)

    return DeviceActionResult(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        requested_state=None,
        message=f"{device.name} command {payload.capability}.{payload.command} sent.",
    )


@app.post("/devices/{device_id}/nest/command", response_model=DeviceActionResult)
async def execute_nest_command(device_id: int, payload: NestCommandRequest) -> DeviceActionResult:
    device = await _load_device_or_404(device_id)
    if not _is_nest(device):
        raise HTTPException(status_code=422, detail="Nest commands are only available for Nest devices.")

    try:
        if payload.command == "set-mode":
            if not payload.mode:
                raise nest_service.NestUnsupportedError("Mode is required.")
            state = await nest_service.set_mode(device, payload.mode)
        elif payload.command == "set-heat":
            if payload.heat_celsius is None:
                raise nest_service.NestUnsupportedError("Heat setpoint is required.")
            state = await nest_service.set_heat(device, payload.heat_celsius)
        elif payload.command == "set-cool":
            if payload.cool_celsius is None:
                raise nest_service.NestUnsupportedError("Cool setpoint is required.")
            state = await nest_service.set_cool(device, payload.cool_celsius)
        elif payload.command == "set-range":
            if payload.heat_celsius is None or payload.cool_celsius is None:
                raise nest_service.NestUnsupportedError("Heat and cool setpoints are required.")
            state = await nest_service.set_range(device, payload.heat_celsius, payload.cool_celsius)
        else:
            raise nest_service.NestUnsupportedError("Unsupported Nest command.")
    except nest_service.NestServiceError as exc:
        _raise_nest_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": state["is_on"], "appliance": state.get("appliance")}))
    return DeviceActionResult(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        requested_state=None,
        is_on=state.get("is_on"),
        message=f"{device.name} Nest thermostat command sent.",
    )


@app.post("/devices/{device_id}/smartthings/view-inside/refresh")
async def refresh_smartthings_view_inside(device_id: int, focus_area: str | None = None) -> DeviceState:
    device = await _load_device_or_404(device_id)
    if not _is_smartthings(device):
        raise HTTPException(status_code=422, detail="View Inside is only available for SmartThings devices.")
    try:
        state = await smartthings_service.refresh_view_inside(device, focus_area)
        await _persist_smartthings_oauth_credentials(device)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": state["is_on"]}))
    return DeviceState(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        is_on=state["is_on"],
        is_open=state.get("is_open"),
        luminance=state.get("luminance"),
        appliance=state.get("appliance"),
        raw=state["raw"],
    )


@app.get("/devices/{device_id}/smartthings/view-inside/images/{file_id}")
async def get_smartthings_view_inside_image(device_id: int, file_id: str) -> Response:
    device = await _load_device_or_404(device_id)
    if not _is_smartthings(device):
        raise HTTPException(status_code=422, detail="View Inside is only available for SmartThings devices.")
    try:
        body, content_type = await smartthings_service.get_view_inside_image(device, file_id)
        await _persist_smartthings_oauth_credentials(device)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)
    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/devices/{device_id}/ring/snapshot")
async def get_ring_snapshot(device_id: int) -> Response:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring snapshots are only available for Ring devices.")
    try:
        body = await ring_service.get_snapshot(device)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)
    return Response(
        content=body,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/devices/{device_id}/ring/snapshot/cached")
async def get_cached_ring_snapshot(device_id: int) -> Response:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring snapshots are only available for Ring devices.")

    snapshot_path = _ring_snapshot_path(device_id)
    if not snapshot_path.exists():
        try:
            await _refresh_ring_snapshot_cache(device)
        except ring_service.RingServiceError as exc:
            _raise_ring_error(exc)

    return FileResponse(
        snapshot_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/devices/{device_id}/ring/snapshot/refresh")
async def refresh_cached_ring_snapshot(device_id: int) -> dict[str, bool]:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring snapshots are only available for Ring devices.")
    try:
        await _refresh_ring_snapshot_cache(device)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)
    return {"ok": True}


@app.get("/devices/{device_id}/ring/alerts", response_model=RingAlertResponse)
async def get_ring_alerts(device_id: int) -> RingAlertResponse:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring alerts are only available for Ring devices.")
    try:
        result = await ring_service.get_active_alerts(device)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)
    return RingAlertResponse(**result)


@app.post("/devices/{device_id}/ring/live-stream")
async def get_ring_live_stream(device_id: int) -> dict:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring live feed is only available for Ring devices.")
    try:
        return await ring_service.get_live_stream(device)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)


@app.post("/devices/{device_id}/ring/webrtc/offer")
async def create_ring_webrtc_offer(device_id: int, payload: RingWebRtcOfferRequest) -> dict:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring live feed is only available for Ring devices.")
    try:
        return await ring_service.create_webrtc_answer(device, payload.sdp_offer)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)


@app.delete("/devices/{device_id}/ring/webrtc/{session_id}", status_code=204)
async def close_ring_webrtc_stream(device_id: int, session_id: str) -> None:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring live feed is only available for Ring devices.")
    await ring_service.close_webrtc_stream(session_id)


@app.post("/devices/{device_id}/ring/webrtc/{session_id}/candidate", status_code=204)
async def send_ring_webrtc_candidate(device_id: int, session_id: str, payload: RingWebRtcCandidateRequest) -> None:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring live feed is only available for Ring devices.")
    try:
        await ring_service.send_webrtc_candidate(session_id, payload.candidate, payload.sdp_m_line_index)
    except ring_service.RingServiceError as exc:
        _raise_ring_error(exc)


@app.get("/devices/{device_id}/ring/webrtc/{session_id}/messages")
async def get_ring_webrtc_messages(device_id: int, session_id: str, since: int = 0) -> dict:
    device = await _load_device_or_404(device_id)
    if not _is_ring(device):
        raise HTTPException(status_code=422, detail="Ring live feed is only available for Ring devices.")
    return ring_service.get_webrtc_messages(session_id, since)


async def _camera_or_404(camera_id: int, *, secrets: bool = False) -> dict:
    camera = await camera_db.get_camera(camera_id, include_secrets=secrets)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return camera


def _camera_error(exc: camera_service.CameraServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@app.get("/api/cameras", response_model=list[CameraOut])
async def list_ip_cameras() -> list[CameraOut]:
    return [CameraOut(**item) for item in await camera_db.list_cameras()]


@app.post("/api/cameras", response_model=CameraOut, status_code=201)
async def create_ip_camera(payload: CameraCreateRequest) -> CameraOut:
    try:
        camera_service._private_host(payload.host)
        main_url = camera_service.validate_stream_url(payload.main_stream_url, payload.host)
        sub_url = camera_service.validate_stream_url(payload.sub_stream_url, payload.host) if payload.sub_stream_url else None
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)
    device = await db.create_device(DeviceCreate(
        name=payload.name, brand="ip-camera", model=payload.model, host=payload.host,
        device_type="camera,onvif,rtsp", channel=0, is_enabled=True,
    ))
    try:
        camera = await camera_db.create_camera(device.id, {
            "username": payload.username,
            "password": payload.password.get_secret_value() if payload.password else None,
            "main_stream_url": main_url, "sub_stream_url": sub_url,
            "recording_enabled": payload.recording_enabled, "audio_enabled": True,
        })
    except Exception:
        await db.delete_device(device.id)
        raise
    return CameraOut(**camera)


@app.get("/api/cameras/{camera_id}", response_model=CameraOut)
async def get_ip_camera(camera_id: int) -> CameraOut:
    return CameraOut(**await _camera_or_404(camera_id))


@app.put("/api/cameras/{camera_id}", response_model=CameraOut)
async def update_ip_camera(camera_id: int, payload: CameraUpdateRequest) -> CameraOut:
    current = await _camera_or_404(camera_id, secrets=True)
    values = payload.model_dump(exclude_unset=True)
    # Audio follows recording automatically; there is no independent audio mode.
    values.pop("audio_enabled", None)
    if values.get("recording_enabled") is True:
        values["audio_enabled"] = True
    if "password" in values:
        values["password"] = payload.password.get_secret_value() if payload.password else None
    host = values.get("host", current["host"])
    try:
        camera_service._private_host(host)
        for key in ("main_stream_url", "sub_stream_url"):
            if values.get(key):
                values[key] = camera_service.validate_stream_url(values[key], host)
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)
    updated = await camera_db.update_camera(camera_id, values)
    return CameraOut(**updated)


@app.delete("/api/cameras/{camera_id}", status_code=204)
async def delete_ip_camera(camera_id: int) -> None:
    if not await camera_db.delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found.")


@app.post("/api/cameras/discover")
async def discover_ip_cameras(payload: CameraDiscoveryRequest) -> dict:
    try:
        return await camera_service.discover_onvif(
            payload.timeout_seconds, payload.subnets, payload.scan_routed_subnets,
        )
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)


@app.post("/api/printers/discover")
async def discover_printers(payload: PrinterDiscoveryRequest) -> dict:
    return await printer_service.discover_printers(
        timeout_seconds=payload.timeout_seconds,
        subnets=payload.subnets,
        scan_routed_subnets=payload.scan_routed_subnets,
        community=payload.community,
        model_hint=payload.model_hint,
    )


@app.post("/api/cameras/onvif-profiles")
async def get_onvif_profiles(payload: CameraOnvifProfilesRequest) -> dict:
    try:
        profiles = await camera_service.onvif_profiles(
            payload.host, payload.port, payload.username,
            payload.password.get_secret_value() if payload.password else None,
        )
        return {"profiles": profiles}
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)


@app.post("/api/cameras/{camera_id}/test")
async def test_ip_camera(camera_id: int) -> dict:
    camera = await _camera_or_404(camera_id, secrets=True)
    try:
        return await camera_service.probe(camera)
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)


@app.get("/api/cameras/{camera_id}/snapshot")
async def get_ip_camera_snapshot(camera_id: int) -> Response:
    camera = await _camera_or_404(camera_id, secrets=True)
    try:
        body = await camera_service.snapshot(camera)
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/device/{device_id}/snapshot")
async def get_ip_camera_snapshot_by_device(device_id: int) -> Response:
    camera = await camera_db.get_camera_by_device(device_id, include_secrets=True)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")
    try:
        body = await camera_service.snapshot(camera)
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{camera_id}/live/{filename}")
async def get_ip_camera_live_file(camera_id: int, filename: str) -> FileResponse:
    camera = await _camera_or_404(camera_id, secrets=True)
    try:
        if filename == "index.m3u8":
            path = await camera_service.ensure_live_stream(camera)
        else:
            await camera_service.ensure_live_stream(camera)
            path = camera_service.safe_live_file(camera_id, filename)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Live segment not found.")
        media_type = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t"
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)


@app.post("/api/cameras/{camera_id}/live/restart")
async def restart_ip_camera_live_stream(camera_id: int) -> dict[str, bool]:
    camera = await _camera_or_404(camera_id, secrets=True)
    try:
        await camera_service.restart_live_stream(camera)
    except camera_service.CameraServiceError as exc:
        _camera_error(exc)
    return {"ok": True}


@app.get("/api/cameras/{camera_id}/recordings")
async def list_camera_recordings(camera_id: int, start: str | None = None, end: str | None = None) -> dict:
    await _camera_or_404(camera_id)
    segments = await camera_db.list_segments(camera_id, start, end)
    return {"segments": [{k: v for k, v in row.items() if k != "relative_path"} | {
        "media_url": f"/api/cameras/{camera_id}/recordings/{row['id']}/media"} for row in segments]}


@app.get("/api/cameras/{camera_id}/recordings/{segment_id}/media")
async def get_camera_recording(camera_id: int, segment_id: int) -> FileResponse:
    segments = await camera_db.list_segments(camera_id)
    segment = next((row for row in segments if row["id"] == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="Recording segment not found.")
    settings = await camera_db.get_settings()
    root = camera_service.recording_root(settings)
    path = (root / segment["relative_path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recording path.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Recording file is missing.")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/camera-settings")
async def get_camera_settings() -> dict:
    settings = await camera_db.get_settings()
    return {"recording_root": settings["recording_root"],
            "capacity_gb": settings["capacity_bytes"] / 1073741824 if settings["capacity_bytes"] else None,
            "reserve_gb": settings["reserve_bytes"] / 1073741824}


@app.put("/api/camera-settings")
async def update_camera_settings(payload: CameraStorageUpdate) -> dict:
    candidate = Path(payload.recording_root).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test_path = candidate / ".sentinel-write-test"
        test_path.write_bytes(b"")
        test_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Recording folder is not writable: {exc}")
    settings = await camera_db.update_settings(
        str(candidate.resolve()), int(payload.capacity_gb * 1073741824) if payload.capacity_gb else None,
        int(payload.reserve_gb * 1073741824),
    )
    return {"recording_root": settings["recording_root"],
            "capacity_gb": settings["capacity_bytes"] / 1073741824 if settings["capacity_bytes"] else None,
            "reserve_gb": settings["reserve_bytes"] / 1073741824}


@app.get("/api/camera-health")
async def get_camera_health() -> dict:
    return await camera_service.health()


@app.get("/devices/{device_id}/cudy/stats", response_model=DeviceState)
async def get_cudy_stats(device_id: int) -> DeviceState:
    device = await _load_device_or_404(device_id)
    if not _is_cudy(device):
        raise HTTPException(status_code=422, detail="Cudy stats are only available for Cudy router devices.")
    try:
        state = await cudy_service.get_stats(device)
    except cudy_service.CudyServiceError as exc:
        _raise_cudy_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": state["is_on"], "appliance": state.get("appliance")}))
    return DeviceState(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        is_on=state["is_on"],
        appliance=state.get("appliance"),
        raw=state["raw"],
    )


@app.post("/devices/{device_id}/cudy/reboot", response_model=DeviceActionResult)
async def reboot_cudy_router(device_id: int, payload: CudyRebootRequest | None = None) -> DeviceActionResult:
    device = await _load_device_or_404(device_id)
    if not _is_cudy(device):
        raise HTTPException(status_code=422, detail="Cudy reboot is only available for Cudy router devices.")
    payload = payload or CudyRebootRequest()
    try:
        result = await cudy_service.reboot(device, target=payload.target)
    except cudy_service.CudyServiceError as exc:
        _raise_cudy_error(exc)

    await db.save_last_state(device_id, json.dumps({"is_on": result.get("is_on")}))
    return DeviceActionResult(
        id=device.id,
        name=device.name,
        host=device.host,
        channel=device.channel,
        requested_state=None,
        is_on=result.get("is_on"),
        message=result.get("message") or f"{device.name} reboot command sent.",
    )


@app.post("/devices/{device_id}/cudy/speedtest")
async def run_cudy_speedtest(device_id: int) -> dict:
    device = await _load_device_or_404(device_id)
    if not _is_cudy(device):
        raise HTTPException(status_code=422, detail="Cudy speed test is only available for Cudy router devices.")
    try:
        return await cudy_service.run_speedtest()
    except cudy_service.CudyServiceError as exc:
        _raise_cudy_error(exc)


@app.post("/scan/network", response_model=NetworkScanResult)
async def scan_network(payload: NetworkScanRequest | None = None) -> NetworkScanResult:
    payload = payload or NetworkScanRequest()
    result = await discovery.scan_network(
        subnet=payload.subnet,
        port=payload.port,
        timeout_seconds=payload.timeout_seconds,
    )
    return NetworkScanResult(**result)


@app.post("/setup/meross-cloud/import", response_model=MerossCloudImportResponse)
async def import_meross_cloud_devices(payload: MerossCloudImportRequest) -> MerossCloudImportResponse:
    try:
        return await cloud_import.import_from_meross_cloud(payload)
    except Exception as exc:
        logger.exception("Meross cloud import failed.")
        raise HTTPException(status_code=502, detail=f"Meross cloud import failed: {exc}")


@app.post("/setup/smartthings/import", response_model=SmartThingsImportResponse)
async def import_smartthings_devices(payload: SmartThingsImportRequest) -> SmartThingsImportResponse:
    try:
        return await smartthings_import.import_from_smartthings(payload)
    except smartthings_service.SmartThingsServiceError as exc:
        _raise_smartthings_error(exc)
    except Exception as exc:
        logger.exception("SmartThings import failed.")
        raise HTTPException(status_code=502, detail=f"SmartThings import failed: {exc}")


@app.post("/setup/smartthings/oauth/start", response_model=SmartThingsOAuthStartResponse)
async def start_smartthings_oauth(payload: SmartThingsOAuthStartRequest) -> SmartThingsOAuthStartResponse:
    state = secrets.token_urlsafe(24)
    await _save_smartthings_oauth_state(state, payload)
    query = urllib.parse.urlencode(
        {
            "client_id": payload.client_id,
            "response_type": "code",
            "redirect_uri": payload.redirect_uri,
            "scope": payload.scopes,
            "state": state,
        },
        quote_via=urllib.parse.quote,
    )
    return SmartThingsOAuthStartResponse(
        authorization_url=f"https://api.smartthings.com/oauth/authorize?{query}",
        state=state,
    )


@app.get("/setup/smartthings/oauth/callback", include_in_schema=False)
async def smartthings_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    if error:
        return Response(
            content=f"SmartThings authorization failed: {error}",
            media_type="text/plain",
            status_code=400,
        )
    if not code:
        return Response(
            content="SmartThings authorization did not include a code.",
            media_type="text/plain",
            status_code=400,
        )
    if not state:
        return Response(
            content=(
                "SmartThings authorization code:\n\n"
                f"{code}\n\n"
                "Paste this code into Sentinel's SmartThings import form."
            ),
            media_type="text/plain",
        )
    try:
        pending = await _load_smartthings_oauth_state(state)
        result = await smartthings_import.import_from_smartthings(
            SmartThingsImportRequest(
                client_id=pending["client_id"],
                client_secret=pending["client_secret"],
                authorization_code=code,
                redirect_uri=pending["redirect_uri"],
                save_devices=bool(pending.get("save_devices", True)),
                exclude_overlaps=bool(pending.get("exclude_overlaps", True)),
            )
        )
    except smartthings_service.SmartThingsServiceError as exc:
        return Response(
            content=f"SmartThings sign-in succeeded, but import failed: {exc.message}",
            media_type="text/plain",
            status_code=exc.status_code,
        )
    except Exception as exc:
        logger.exception("SmartThings OAuth callback import failed.")
        return Response(
            content=f"SmartThings sign-in succeeded, but import failed: {exc}",
            media_type="text/plain",
            status_code=502,
        )

    return Response(
        content=(
            "<!doctype html><html><head><title>SmartThings connected</title></head>"
            "<body>"
            "<h1>SmartThings connected</h1>"
            f"<p>Imported {len(result.imported)} SmartThings device(s); skipped {len(result.skipped)} overlap(s).</p>"
            "<p><a href=\"/dashboard\">Return to Sentinel dashboard</a></p>"
            "</body></html>"
        ),
        media_type="text/html",
    )


@app.get("/setup/nest/oauth/callback", include_in_schema=False)
async def nest_oauth_callback(code: str | None = None, error: str | None = None) -> Response:
    if error:
        return Response(
            content=f"Google Nest authorization failed: {error}",
            media_type="text/plain",
            status_code=400,
        )
    if not code:
        return Response(
            content="Google Nest authorization did not include a code.",
            media_type="text/plain",
            status_code=400,
        )
    return Response(
        content=(
            "Google Nest authorization code:\n\n"
            f"{code}\n\n"
            "Paste this code into Sentinel's Nest import form."
        ),
        media_type="text/plain",
    )


@app.post("/setup/nest/import", response_model=NestImportResponse)
async def import_nest_devices(payload: NestImportRequest) -> NestImportResponse:
    try:
        return await nest_import.import_from_nest(payload)
    except nest_service.NestServiceError as exc:
        _raise_nest_error(exc)
    except Exception as exc:
        logger.exception("Nest import failed.")
        raise HTTPException(status_code=502, detail=f"Nest import failed: {exc}")


@app.post("/setup/ring/import", response_model=RingImportResponse)
async def import_ring_devices(payload: RingImportRequest) -> RingImportResponse:
    try:
        return await ring_import.import_from_ring(payload)
    except Exception as exc:
        logger.exception("Ring import failed.")
        raise HTTPException(status_code=502, detail=f"Ring import failed: {exc}")


@app.post("/setup/yale/import", response_model=YaleImportResponse)
async def import_yale_devices(payload: YaleImportRequest) -> YaleImportResponse:
    try:
        return await yale_import.import_from_yale(payload)
    except Exception as exc:
        logger.exception("Yale import failed.")
        raise HTTPException(status_code=502, detail=f"Yale import failed: {exc}")
