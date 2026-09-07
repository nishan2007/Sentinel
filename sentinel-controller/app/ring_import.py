import json

from ring_doorbell import Auth, Ring
from ring_doorbell.exceptions import AuthenticationError, Requires2FAError, RingError

from app import db
from app.schemas import DeviceCreate, RingImportedDevice, RingImportRequest, RingImportResponse
from app.source_registry import disable_lower_priority_overlaps, find_overlaps


USER_AGENT = "sentinel/0.1"


async def _login(payload: RingImportRequest) -> tuple[Ring | None, dict | None, bool]:
    token_holder: dict = {}

    def token_updater(token: dict) -> None:
        token_holder.clear()
        token_holder.update(token)

    auth = Auth(USER_AGENT, token_updater=token_updater)
    try:
        token = await auth.async_fetch_token(
            payload.email,
            payload.password.get_secret_value(),
            payload.otp_code,
        )
    except Requires2FAError:
        return None, None, True
    except AuthenticationError as exc:
        raise RuntimeError("Ring login failed. Check the email, password, and OTP code.") from exc
    except RingError as exc:
        raise RuntimeError(f"Ring API error: {exc}") from exc

    if not token_holder:
        token_holder.update(token)
    ring = Ring(Auth(USER_AGENT, token_holder))
    await ring.async_update_data()
    return ring, token_holder, False


async def import_from_ring(payload: RingImportRequest) -> RingImportResponse:
    ring, token, requires_2fa = await _login(payload)
    if requires_2fa:
        return RingImportResponse(
            imported=[],
            skipped=[],
            requires_2fa=True,
            note="Ring requires a two-factor code. Enter the code and import again.",
        )
    if ring is None or token is None:
        raise RuntimeError("Ring login did not return account data.")

    existing = await db.list_devices()
    imported: list[RingImportedDevice] = []
    skipped: list[RingImportedDevice] = []
    token_json = json.dumps(token)

    for ring_device in ring.get_device_list():
        api_id = str(ring_device.device_api_id)
        name = ring_device.name
        overlaps = find_overlaps(
            existing,
            source="ring",
            name=name,
            external_id=api_id,
            host=f"ring:{api_id}",
        ) if payload.exclude_overlaps else []
        same_or_higher = [item for item in overlaps if item.device.brand.lower() == "ring"]
        reason = f"already imported as Ring device #{same_or_higher[0].device.id}" if same_or_higher else None

        record = RingImportedDevice(
            name=name,
            device_uuid=api_id,
            device_type=f"{ring_device.family},{ring_device.kind}",
            model=ring_device.model,
            saved=False,
            skipped=bool(reason),
            skip_reason=reason,
        )
        if reason:
            skipped.append(record)
            continue

        disabled = await disable_lower_priority_overlaps(
            source="ring",
            name=name,
            external_id=api_id,
            host=f"ring:{api_id}",
        ) if payload.exclude_overlaps else []
        record.disabled_overlaps = [f"{item.device.name} ({item.device.brand})" for item in disabled]

        if payload.save_devices:
            saved = await db.upsert_imported_device(
                DeviceCreate(
                    name=name,
                    brand="ring",
                    model=ring_device.model,
                    host=f"ring:{api_id}",
                    device_key=token_json,
                    device_uuid=api_id,
                    device_type=f"{ring_device.family},{ring_device.kind}",
                    channel=0,
                    is_enabled=True,
                )
            )
            record.id = saved.id
            record.saved = True
        imported.append(record)

    return RingImportResponse(
        imported=imported,
        skipped=skipped,
        note="Ring tokens are stored only on imported Ring device records. Native Ring rows hide lower-priority SmartThings overlaps with the same name or ID.",
    )
