import aiohttp
from yalexs.api_async import ApiAsync
from yalexs.authenticator_async import AuthenticatorAsync
from yalexs.authenticator_common import AuthenticationState, ValidationResult
from yalexs.const import Brand
from yalexs.exceptions import AugustApiAIOHTTPError

from app import db
from app.schemas import DeviceCreate, YaleImportedDevice, YaleImportRequest, YaleImportResponse
from app.source_registry import disable_lower_priority_overlaps, find_overlaps


def _brand(value: str) -> Brand:
    try:
        return Brand(value)
    except ValueError:
        return Brand.YALE_ACCESS


async def _access_token_from_payload(payload: YaleImportRequest, api: ApiAsync) -> tuple[str | None, bool, str | None]:
    if payload.access_token is not None:
        return payload.access_token.get_secret_value(), False, None

    if not payload.email or payload.password is None:
        raise RuntimeError("Enter either a Yale access token or your Yale email and password.")

    authenticator = AuthenticatorAsync(
        api,
        payload.login_method,
        payload.email,
        payload.password.get_secret_value(),
    )
    await authenticator.async_setup_authentication()
    authentication = await authenticator.async_authenticate()

    if authentication.state is AuthenticationState.BAD_PASSWORD:
        raise RuntimeError("Yale login failed. Check the email and password.")

    if authentication.state is AuthenticationState.REQUIRES_VALIDATION:
        if not payload.verification_code:
            await authenticator.async_send_verification_code()
            return None, True, "Yale sent a verification code. Enter it and import again."
        validation = await authenticator.async_validate_verification_code(payload.verification_code)
        if validation is not ValidationResult.VALIDATED:
            raise RuntimeError("Yale verification code was rejected.")
        authentication.state = AuthenticationState.AUTHENTICATED

    if authentication.state is not AuthenticationState.AUTHENTICATED or not authentication.access_token:
        raise RuntimeError("Yale login did not return an access token.")
    return authentication.access_token, False, None


async def import_from_yale(payload: YaleImportRequest) -> YaleImportResponse:
    async with aiohttp.ClientSession() as session:
        api = ApiAsync(session, brand=_brand(payload.brand))
        token, requires_validation, validation_note = await _access_token_from_payload(payload, api)
        if requires_validation or token is None:
            return YaleImportResponse(
                imported=[],
                skipped=[],
                requires_validation=True,
                note=validation_note or "Yale requires verification. Enter the code and import again.",
            )
        try:
            locks = await api.async_get_operable_locks(token)
        except AugustApiAIOHTTPError as exc:
            if exc.auth_failed:
                raise RuntimeError("Yale token was rejected. Check that the token is current and has lock access.") from exc
            raise RuntimeError(f"Yale API error: {exc}") from exc

    existing = await db.list_devices()
    imported: list[YaleImportedDevice] = []
    skipped: list[YaleImportedDevice] = []

    for lock in locks:
        overlaps = find_overlaps(
            existing,
            source="yale",
            name=lock.device_name,
            external_id=lock.device_id,
            host=f"yale:{lock.device_id}",
        ) if payload.exclude_overlaps else []
        same_or_higher = [item for item in overlaps if item.device.brand.lower() == "yale"]
        reason = f"already imported as Yale lock #{same_or_higher[0].device.id}" if same_or_higher else None
        record = YaleImportedDevice(
            name=lock.device_name,
            device_uuid=lock.device_id,
            house_id=lock.house_id,
            saved=False,
            skipped=bool(reason),
            skip_reason=reason,
        )
        if reason:
            skipped.append(record)
            continue

        disabled = await disable_lower_priority_overlaps(
            source="yale",
            name=lock.device_name,
            external_id=lock.device_id,
            host=f"yale:{lock.device_id}",
        ) if payload.exclude_overlaps else []
        record.disabled_overlaps = [f"{item.device.name} ({item.device.brand})" for item in disabled]

        if payload.save_devices:
            saved = await db.upsert_imported_device(
                DeviceCreate(
                    name=lock.device_name,
                    brand="yale",
                    model=_brand(payload.brand).value,
                    host=f"yale:{lock.device_id}",
                    device_key=token,
                    device_uuid=lock.device_id,
                    device_type="lock",
                    channel=0,
                    is_enabled=True,
                )
            )
            record.id = saved.id
            record.saved = True
        imported.append(record)

    return YaleImportResponse(
        imported=imported,
        skipped=skipped,
        requires_validation=False,
        note="Yale native lock rows hide lower-priority SmartThings overlaps with the same lock name or ID.",
    )
