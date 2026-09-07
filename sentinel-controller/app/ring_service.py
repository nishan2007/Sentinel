import asyncio
import json
from typing import Any

from ring_doorbell import Auth, Ring
from ring_doorbell.const import API_URI, DEVICES_ENDPOINT, DINGS_ENDPOINT, SNAPSHOT_ENDPOINT
from ring_doorbell.exceptions import AuthenticationError, RingError
from ring_doorbell.webrtcstream import RingWebRtcStream

from app.models import Device


USER_AGENT = "sentinel/0.1"
_ACTIVE_WEBRTC_STREAMS: dict[str, dict[str, Any]] = {}
_RING_CLIENT_CACHE: dict[int, tuple[str, Ring]] = {}


class RingServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class MissingRingTokenError(RingServiceError):
    status_code = 400


class RingAuthError(RingServiceError):
    status_code = 401


def _stored_token(device: Device) -> dict[str, Any]:
    if not device.device_key:
        raise MissingRingTokenError("Ring token is missing for this device.")
    try:
        token = json.loads(device.device_key)
    except json.JSONDecodeError as exc:
        raise MissingRingTokenError("Stored Ring token is invalid JSON.") from exc
    if not isinstance(token, dict):
        raise MissingRingTokenError("Stored Ring token has the wrong shape.")
    return token


async def _client_from_token(token: dict[str, Any]) -> Ring:
    auth = Auth(USER_AGENT, token)
    ring = Ring(auth)
    try:
        devices_resp = await auth.async_query(API_URI + DEVICES_ENDPOINT)
        devices_data = devices_resp.json()
        ring.devices_data = {
            device_type: {obj["id"]: obj for obj in devices}
            for device_type, devices in devices_data.items()
        }
        dings_resp = await auth.async_query(API_URI + DINGS_ENDPOINT)
        ring.dings_data = dings_resp.json()
        ring.groups_data = {}
        ring.session = {"source": "direct-api"}
    except AuthenticationError as exc:
        await auth.async_close()
        raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
    except RingError as exc:
        await auth.async_close()
        raise RingServiceError(f"Ring API error: {exc}") from exc
    except Exception:
        await auth.async_close()
        raise
    return ring


async def _client_from_device(device: Device) -> Ring:
    token = _stored_token(device)
    api_id = _ring_api_id(device)
    token_signature = json.dumps(token, sort_keys=True)
    cached = _RING_CLIENT_CACHE.get(api_id)
    if cached and cached[0] == token_signature:
        return cached[1]

    ring = await _client_from_token(token)
    _RING_CLIENT_CACHE[api_id] = (token_signature, ring)
    return ring


def _ring_api_id(device: Device) -> int:
    try:
        return int(device.device_uuid or device.host.split(":", 1)[1])
    except (IndexError, TypeError, ValueError) as exc:
        raise RingServiceError("Ring device ID is missing or invalid.") from exc


async def _get_ring_client_and_device(device: Device) -> tuple[Ring, Any]:
    ring = await _client_from_device(device)
    api_id = _ring_api_id(device)
    ring_device = ring.get_device_by_api_id(api_id)
    if ring_device is None:
        raise RingServiceError("Ring device was not found in this account.")
    return ring, ring_device


async def _get_ring_device(device: Device):
    _, ring_device = await _get_ring_client_and_device(device)
    return ring_device


async def get_status(device: Device) -> dict[str, Any]:
    ring_device = await _get_ring_device(device)

    connection = getattr(ring_device, "connection_status", None)
    battery = getattr(ring_device, "battery_life", None)
    raw = {
        "name": ring_device.name,
        "family": ring_device.family,
        "kind": ring_device.kind,
        "model": ring_device.model,
        "device_id": ring_device.device_id,
        "connection_status": connection,
        "battery_life": battery,
        "subscribed": getattr(ring_device, "subscribed", None),
        "wifi_name": getattr(ring_device, "wifi_name", None),
        "wifi_signal_strength": getattr(ring_device, "wifi_signal_strength", None),
        "wifi_signal_category": getattr(ring_device, "wifi_signal_category", None),
    }
    return {
        "is_on": connection != "offline",
        "raw": raw,
    }


async def get_active_alerts(device: Device) -> dict[str, Any]:
    ring = await _client_from_device(device)
    api_id = _ring_api_id(device)
    try:
        response = await ring.auth.async_query(API_URI + DINGS_ENDPOINT)
        active_dings = response.json()
    except AuthenticationError as exc:
        await _evict_cached_client(api_id, ring)
        raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
    except RingError as exc:
        raise RingServiceError(f"Ring alert check failed: {exc}") from exc

    alerts = []
    for ding in active_dings or []:
        doorbot_id = ding.get("doorbot_id") or ding.get("doorbotId")
        if str(doorbot_id) != str(api_id):
            continue
        now = ding.get("now")
        expires_in = ding.get("expires_in")
        expires_at = None
        if isinstance(now, (int, float)) and isinstance(expires_in, (int, float)):
            expires_at = now + expires_in
        alerts.append(
            {
                "id": str(ding.get("id") or f"{doorbot_id}:{ding.get('kind')}:{ding.get('now')}"),
                "kind": ding.get("kind"),
                "state": ding.get("state"),
                "device_name": ding.get("doorbot_description") or ding.get("device_name"),
                "expires_at": expires_at,
            }
        )
    return {
        "active": bool(alerts),
        "alerts": alerts,
    }


async def get_snapshot(device: Device) -> bytes:
    ring, ring_device = await _get_ring_client_and_device(device)
    api_id = _ring_api_id(device)
    try:
        snapshot = await ring_device.async_get_snapshot(retries=6, delay=1)
    except AuthenticationError as exc:
        await _evict_cached_client(api_id, ring)
        raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
    if not snapshot:
        try:
            response = await ring_device._ring.async_query(SNAPSHOT_ENDPOINT.format(ring_device._attrs.get("id")))  # noqa: SLF001
            if response.status_code == 200 and response.content:
                snapshot = response.content
        except AuthenticationError as exc:
            await _evict_cached_client(api_id, ring)
            raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
        except RingError:
            snapshot = None
    if not snapshot:
        raise RingServiceError("Ring snapshot is unavailable right now.")
    return snapshot


async def get_live_stream(device: Device) -> dict[str, Any]:
    ring, ring_device = await _get_ring_client_and_device(device)
    api_id = _ring_api_id(device)
    try:
        live = await ring_device.async_get_live_streaming_json()
    except AuthenticationError as exc:
        await _evict_cached_client(api_id, ring)
        raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
    except RingError as exc:
        raise RingServiceError(f"Ring live metadata is unavailable: {exc}") from exc
    if not live:
        raise RingServiceError("Ring live stream did not return a playable session.")
    return {
        "device_id": getattr(ring_device, "device_id", None),
        "device_api_id": getattr(ring_device, "device_api_id", None),
        "name": getattr(ring_device, "name", None),
        "live": live,
    }


async def create_webrtc_answer(device: Device, sdp_offer: str) -> dict[str, Any]:
    session_id = RingWebRtcStream.get_sdp_session_id(sdp_offer)
    if not session_id:
        raise RingServiceError("Could not read a WebRTC session ID from the browser offer.")

    await close_webrtc_stream(session_id)
    ring, ring_device = await _get_ring_client_and_device(device)
    messages: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    answer_future: asyncio.Future[str] = loop.create_future()

    def on_ring_message(message: Any) -> None:
        if getattr(message, "answer", None):
            if not answer_future.done():
                answer_future.set_result(message.answer)
            return
        if getattr(message, "candidate", None):
            messages.append(
                {
                    "type": "candidate",
                    "candidate": message.candidate,
                    "sdp_m_line_index": message.sdp_m_line_index or 0,
                }
            )
            return
        if getattr(message, "error_code", None) or getattr(message, "error_message", None):
            error = {
                "type": "error",
                "error_code": message.error_code,
                "error_message": message.error_message,
            }
            messages.append(error)
            if not answer_future.done():
                answer_future.set_exception(RingServiceError(message.error_message or "Ring WebRTC live feed failed."))

    try:
        _ACTIVE_WEBRTC_STREAMS[session_id] = {
            "ring": ring,
            "ring_device": ring_device,
            "messages": messages,
        }
        await ring_device.generate_async_webrtc_stream(
            sdp_offer,
            session_id,
            on_ring_message,
            keep_alive_timeout=180,
        )
        sdp_answer = await asyncio.wait_for(answer_future, timeout=10)
        messages.append({"type": "answer-ready"})
    except AuthenticationError as exc:
        await close_webrtc_stream(session_id)
        await _evict_cached_client(_ring_api_id(device), ring)
        raise RingAuthError("Ring token was rejected. Re-import Ring devices with a fresh login.") from exc
    except asyncio.TimeoutError as exc:
        await close_webrtc_stream(session_id)
        raise RingServiceError("Ring WebRTC live feed timed out waiting for video signaling.") from exc
    except RingError as exc:
        await close_webrtc_stream(session_id)
        raise RingServiceError(f"Ring WebRTC live feed failed: {exc}") from exc

    return {
        "session_id": session_id,
        "sdp_answer": sdp_answer,
    }


async def close_webrtc_stream(session_id: str) -> None:
    active = _ACTIVE_WEBRTC_STREAMS.pop(session_id, None)
    if not active:
        return
    ring_device = active["ring_device"]
    try:
        await ring_device.close_webrtc_stream(session_id)
    except RingError:
        return


async def _close_ring_client(ring: Ring) -> None:
    auth = getattr(ring, "auth", None)
    close = getattr(auth, "async_close", None)
    if close:
        await close()


async def _evict_cached_client(api_id: int, ring: Ring | None = None) -> None:
    cached = _RING_CLIENT_CACHE.get(api_id)
    if cached is None:
        if ring is not None:
            await _close_ring_client(ring)
        return
    cached_ring = cached[1]
    if ring is None or cached_ring is ring:
        _RING_CLIENT_CACHE.pop(api_id, None)
        await _close_ring_client(cached_ring)


async def close_cached_clients() -> None:
    cached_clients = list(_RING_CLIENT_CACHE.values())
    _RING_CLIENT_CACHE.clear()
    for _, ring in cached_clients:
        await _close_ring_client(ring)


async def send_webrtc_candidate(session_id: str, candidate: str, sdp_m_line_index: int) -> None:
    active = _ACTIVE_WEBRTC_STREAMS.get(session_id)
    if not active:
        raise RingServiceError("Ring WebRTC session is no longer active.")
    ring_device = active["ring_device"]
    try:
        await ring_device.on_webrtc_candidate(session_id, candidate, sdp_m_line_index)
    except RingError as exc:
        raise RingServiceError(f"Ring WebRTC candidate failed: {exc}") from exc


def get_webrtc_messages(session_id: str, since: int = 0) -> dict[str, Any]:
    active = _ACTIVE_WEBRTC_STREAMS.get(session_id)
    if not active:
        return {
            "messages": [{"type": "closed", "error_message": "Ring WebRTC session is no longer active."}],
            "next": since,
        }
    messages = active["messages"]
    safe_since = max(0, min(since, len(messages)))
    return {
        "messages": messages[safe_since:],
        "next": len(messages),
    }
