import asyncio
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import subprocess
import ssl
import tempfile
import urllib.parse
from typing import Any

from app import camera_db


class CameraServiceError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _resolve_tool(env_name: str, binary: str) -> str | None:
    configured = os.getenv(env_name)
    if configured:
        return configured
    discovered = shutil.which(binary)
    if discovered:
        return discovered
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidate = Path(prefix) / "opt" / "ffmpeg" / "bin" / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


FFMPEG_PATH = _resolve_tool("SENTINEL_FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = _resolve_tool("SENTINEL_FFPROBE_PATH", "ffprobe")
LIVE_ROOT = Path(tempfile.gettempdir()) / "sentinel-camera-live"
RECORDING_SEGMENT_SECONDS = 60
_recorder_tasks: dict[int, asyncio.Task] = {}
_recorder_processes: dict[int, asyncio.subprocess.Process] = {}
_live_processes: dict[int, asyncio.subprocess.Process] = {}
_live_touched: dict[int, float] = {}
_manager_task: asyncio.Task | None = None
_stopping = False
_camera_errors: dict[int, str] = {}


def _redact(message: str, camera: dict) -> str:
    safe = message
    for secret in (camera.get("password"), camera.get("username")):
        if secret:
            safe = safe.replace(str(secret), "***")
            safe = safe.replace(urllib.parse.quote(str(secret), safe=""), "***")
    try:
        safe = safe.replace(_credential_url(camera), camera.get("main_stream_url", "[camera stream]"))
    except Exception:
        pass
    return safe


def _private_host(host: str) -> str:
    candidate = host.strip().strip("[]")
    try:
        addresses = socket.getaddrinfo(candidate, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CameraServiceError("Camera host could not be resolved.") from exc
    ips = {item[4][0].split("%", 1)[0] for item in addresses}
    if not ips:
        raise CameraServiceError("Camera host did not resolve to an address.")
    for value in ips:
        address = ipaddress.ip_address(value)
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise CameraServiceError("Camera streams must resolve to a private or local network address.")
    return candidate


def validate_stream_url(url: str, expected_host: str | None = None) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise CameraServiceError("Camera stream must be an RTSP or RTSPS URL.")
    _private_host(parsed.hostname)
    if expected_host:
        expected_ips = {x[4][0] for x in socket.getaddrinfo(_private_host(expected_host), None)}
        stream_ips = {x[4][0] for x in socket.getaddrinfo(parsed.hostname, None)}
        if expected_ips.isdisjoint(stream_ips):
            raise CameraServiceError("The stream URL must point to the configured camera host.")
    clean_netloc = parsed.hostname
    if parsed.port:
        clean_netloc += f":{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), clean_netloc, parsed.path or "/", parsed.query, ""))


def _credential_url(camera: dict, *, substream: bool = False) -> str:
    raw = camera.get("sub_stream_url") if substream and camera.get("sub_stream_url") else camera["main_stream_url"]
    parsed = urllib.parse.urlsplit(raw)
    username = camera.get("username") or parsed.username
    password = camera.get("password") or parsed.password
    auth = ""
    if username:
        auth = urllib.parse.quote(username, safe="")
        if password:
            auth += ":" + urllib.parse.quote(password, safe="")
        auth += "@"
    host = parsed.hostname or ""
    netloc = auth + host + (f":{parsed.port}" if parsed.port else "")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


async def probe(camera: dict) -> dict:
    if not FFPROBE_PATH:
        raise CameraServiceError("FFprobe is not installed. Install FFmpeg or set SENTINEL_FFPROBE_PATH.", 503)
    url = _credential_url(camera)
    process = await asyncio.create_subprocess_exec(
        FFPROBE_PATH, "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,width,height",
        "-of", "json", "-rtsp_transport", "tcp", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except asyncio.TimeoutError:
        process.kill(); await process.wait()
        raise CameraServiceError("Camera connection timed out.", 504)
    if process.returncode:
        raise CameraServiceError("Camera rejected the stream URL or credentials.")
    import json
    data = json.loads(stdout or b"{}")
    streams = data.get("streams", [])
    if not any(item.get("codec_type") == "video" for item in streams):
        raise CameraServiceError("The RTSP source did not contain a video stream.")
    return {"ok": True, "streams": streams}


async def snapshot(camera: dict) -> bytes:
    if not FFMPEG_PATH:
        raise CameraServiceError("FFmpeg is not installed.", 503)
    process = await asyncio.create_subprocess_exec(
        FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
        "-i", _credential_url(camera, substream=True), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        body, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except asyncio.TimeoutError:
        process.kill(); await process.wait()
        raise CameraServiceError("Camera snapshot timed out.", 504)
    if process.returncode or not body:
        raise CameraServiceError("Camera snapshot is unavailable.", 502)
    return body


def recording_root(settings: dict) -> Path:
    configured = os.getenv("SENTINEL_RECORDING_ROOT") or settings["recording_root"]
    root = Path(configured).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root.resolve()


async def _record_camera(camera_id: int) -> None:
    delay = 2
    while not _stopping:
        camera = await camera_db.get_camera(camera_id, include_secrets=True)
        if not camera or not camera["recording_enabled"]:
            return
        if not FFMPEG_PATH:
            _camera_errors[camera_id] = "FFmpeg is not installed."
            return
        settings = await camera_db.get_settings()
        root = recording_root(settings)
        folder = root / str(camera_id)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            output = str(folder / "%Y%m%d-%H%M%S.mp4.part")
            command = [
                FFMPEG_PATH, "-hide_banner", "-loglevel", "warning", "-rtsp_transport", "tcp",
                "-i", _credential_url(camera), "-map", "0:v:0",
            ]
            # Recording is one operation: always preserve the camera's audio track
            # when its main RTSP stream provides one. The optional map keeps
            # video-only cameras working without a separate audio setting.
            command += ["-map", "0:a:0?"]
            command += [
                "-c", "copy", "-f", "segment", "-segment_time", str(RECORDING_SEGMENT_SECONDS),
                "-reset_timestamps", "1",
                "-strftime", "1", "-segment_format", "mp4", output,
            ]
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _recorder_processes[camera_id] = process
            _camera_errors.pop(camera_id, None)
            _, stderr = await process.communicate()
            if not _stopping:
                message = stderr.decode("utf-8", "replace").strip().splitlines()
                detail = message[-1] if message else "Recorder stopped unexpectedly."
                _camera_errors[camera_id] = _redact(detail, camera)[:300]
        except (OSError, CameraServiceError) as exc:
            _camera_errors[camera_id] = str(exc)[:300]
        finally:
            _recorder_processes.pop(camera_id, None)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


async def reconcile_segments() -> None:
    settings = await camera_db.get_settings()
    root = recording_root(settings)
    if not root.exists():
        return
    cameras = await camera_db.list_cameras(include_secrets=True)
    indexed = {row["relative_path"]: row for row in await camera_db.oldest_segments()}
    now = datetime.now(timezone.utc).timestamp()
    for camera in cameras:
        folder = root / str(camera["id"])
        if not folder.exists():
            continue
        for partial in folder.glob("*.mp4.part"):
            try:
                if now - partial.stat().st_mtime < 20:
                    continue
                if FFPROBE_PATH:
                    check = await asyncio.create_subprocess_exec(
                        FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                        str(partial), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    )
                    output, _ = await check.communicate()
                    if check.returncode or not output.strip():
                        continue
                partial.replace(partial.with_suffix(""))
            except OSError:
                continue
        for path in folder.glob("*.mp4"):
            try:
                stat = path.stat()
                if stat.st_size == 0 or now - stat.st_mtime < 20:
                    continue
                relative = path.resolve().relative_to(root).as_posix()
                existing = indexed.get(relative)
                duration = existing["duration_seconds"] if existing and existing["duration_seconds"] != 10.0 else await _media_duration(path)
                duration = duration or 10.0
                started = _segment_started_at(path, stat.st_mtime, duration)
                await camera_db.upsert_segment(camera["id"], relative, started, duration, stat.st_size)
            except (OSError, ValueError):
                continue


async def _media_duration(path: Path) -> float | None:
    if not FFPROBE_PATH:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await process.communicate()
        if process.returncode or not output.strip():
            return None
        duration = float(output.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError):
        return None


def _segment_started_at(path: Path, modified_at: float, duration_seconds: float) -> str:
    try:
        # FFmpeg creates names like 20260722-143719.mp4 using the host's local
        # timezone. Converting that local wall time to UTC gives the true start.
        local_start = datetime.strptime(path.stem, "%Y%m%d-%H%M%S").astimezone()
        return local_start.astimezone(timezone.utc).isoformat()
    except ValueError:
        # Legacy or custom names have no embedded timestamp. Their mtime is
        # approximately the finalized end, so derive the start from duration.
        return datetime.fromtimestamp(modified_at - duration_seconds, timezone.utc).isoformat()


async def enforce_storage_limits() -> None:
    settings = await camera_db.get_settings()
    root = recording_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    segments = await camera_db.oldest_segments()
    total = sum(int(row["size_bytes"]) for row in segments)
    capacity = settings.get("capacity_bytes")
    reserve = int(settings["reserve_bytes"])
    for row in segments:
        if (capacity is None or total <= capacity) and usage.free >= reserve:
            break
        try:
            path = (root / row["relative_path"]).resolve()
            path.relative_to(root)
            size = path.stat().st_size if path.exists() else int(row["size_bytes"])
            if path.exists():
                path.unlink()
            total -= size
        except (OSError, ValueError):
            pass
        await camera_db.delete_segment(row["id"])
        usage = shutil.disk_usage(root)


async def _manager_loop() -> None:
    while not _stopping:
        cameras = await camera_db.list_cameras(include_secrets=True)
        active_ids = {item["id"] for item in cameras if item["recording_enabled"]}
        for camera_id in active_ids:
            task = _recorder_tasks.get(camera_id)
            if not task or task.done():
                _recorder_tasks[camera_id] = asyncio.create_task(_record_camera(camera_id))
        for camera_id, task in list(_recorder_tasks.items()):
            if camera_id not in active_ids:
                task.cancel(); _recorder_tasks.pop(camera_id, None)
                process = _recorder_processes.get(camera_id)
                if process and process.returncode is None:
                    process.terminate()
        await reconcile_segments()
        await enforce_storage_limits()
        await _stop_idle_live_streams()
        await asyncio.sleep(15)


async def start_manager() -> None:
    global _manager_task, _stopping
    _stopping = False
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    _manager_task = asyncio.create_task(_manager_loop())


async def stop_manager() -> None:
    global _stopping
    _stopping = True
    if _manager_task:
        _manager_task.cancel()
    for process in [*_recorder_processes.values(), *_live_processes.values()]:
        if process.returncode is None:
            process.terminate()
    await asyncio.gather(*[p.wait() for p in [*_recorder_processes.values(), *_live_processes.values()]], return_exceptions=True)
    for task in _recorder_tasks.values():
        task.cancel()


async def ensure_live_stream(camera: dict) -> Path:
    if not FFMPEG_PATH:
        raise CameraServiceError("FFmpeg is not installed.", 503)
    camera_id = camera["id"]
    _live_touched[camera_id] = asyncio.get_running_loop().time()
    folder = LIVE_ROOT / str(camera_id)
    playlist = folder / "index.m3u8"
    process = _live_processes.get(camera_id)
    if process and process.returncode is None:
        return playlist
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    process = await asyncio.create_subprocess_exec(
        FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
        "-i", _credential_url(camera, substream=True), "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-c:a", "aac",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-f", "hls", "-hls_time", "2", "-hls_list_size", "5",
        "-hls_flags", "delete_segments+append_list+omit_endlist", str(playlist),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _live_processes[camera_id] = process
    for _ in range(100):
        if playlist.exists():
            return playlist
        if process.returncode is not None:
            break
        await asyncio.sleep(0.2)
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
    stderr = b""
    if process.stderr:
        try:
            stderr = await asyncio.wait_for(process.stderr.read(), timeout=1)
        except asyncio.TimeoutError:
            stderr = b""
    _live_processes.pop(camera_id, None)
    lines = stderr.decode("utf-8", "replace").strip().splitlines()
    if lines:
        _camera_errors[camera_id] = _redact(lines[-1], camera)[:300]
    raise CameraServiceError("Camera live stream did not start.", 502)


async def restart_live_stream(camera: dict) -> Path:
    camera_id = camera["id"]
    process = _live_processes.pop(camera_id, None)
    if process and process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
    _live_touched.pop(camera_id, None)
    shutil.rmtree(LIVE_ROOT / str(camera_id), ignore_errors=True)
    return await ensure_live_stream(camera)


async def _stop_idle_live_streams() -> None:
    now = asyncio.get_running_loop().time()
    for camera_id, process in list(_live_processes.items()):
        if now - _live_touched.get(camera_id, 0) > 60:
            if process.returncode is None:
                process.terminate()
            _live_processes.pop(camera_id, None)


def safe_live_file(camera_id: int, filename: str) -> Path:
    folder = (LIVE_ROOT / str(camera_id)).resolve()
    path = (folder / filename).resolve()
    try:
        path.relative_to(folder)
    except ValueError as exc:
        raise CameraServiceError("Invalid live media path.", 400) from exc
    return path


async def health() -> dict:
    settings = await camera_db.get_settings()
    root = recording_root(settings)
    try:
        root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(root)
        storage = {"root": str(root), "free_bytes": usage.free, "total_bytes": usage.total,
                   "capacity_bytes": settings.get("capacity_bytes"), "reserve_bytes": settings["reserve_bytes"],
                   "writable": os.access(root, os.W_OK)}
    except OSError as exc:
        storage = {"root": str(root), "writable": False, "error": str(exc)}
    cameras = await camera_db.list_cameras()
    return {
        "status": "ok" if FFMPEG_PATH and storage.get("writable") else "needs_attention",
        "ffmpeg": {"available": bool(FFMPEG_PATH), "path": FFMPEG_PATH},
        "storage": storage,
        "cameras": [{"id": item["id"], "recording": item["id"] in _recorder_processes,
                     "error": _camera_errors.get(item["id"])} for item in cameras],
    }


def routed_private_subnets() -> list[str]:
    configured = [value.strip() for value in os.getenv("SENTINEL_CAMERA_SUBNETS", "").split(",") if value.strip()]
    candidates = list(configured)
    commands = []
    if os.name == "nt":
        commands = [["route", "print", "-4"]]
    elif shutil.which("ip"):
        commands = [["ip", "-4", "route"]]
    else:
        commands = [["netstat", "-rn", "-f", "inet"]]
    try:
        output = subprocess.run(commands[0], capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        output = ""
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        token = parts[0]
        if token in {"default", "0.0.0.0", "127", "224.0.0/4", "255.255.255.255/32"}:
            continue
        command_name = commands[0][0]
        if command_name == "netstat" and (len(parts) < 2 or parts[1].startswith("link#")):
            continue
        if command_name == "ip" and "via" not in parts:
            continue
        if os.name == "nt" and any(part.lower() == "on-link" for part in parts):
            continue
        try:
            if os.name == "nt" and len(parts) >= 2 and "." in parts[1]:
                network = ipaddress.ip_network(f"{parts[0]}/{parts[1]}", strict=False)
            else:
                address_part, separator, prefix = token.partition("/")
                octets = address_part.split(".")
                if separator and len(octets) < 4:
                    address_part += ".0" * (4 - len(octets))
                    token = f"{address_part}/{prefix}"
                elif "/" not in token:
                    if len(octets) == 3:
                        token += "/24"
                    elif len(octets) == 2:
                        token += ".0/24"
                    else:
                        continue
                network = ipaddress.ip_network(token, strict=False)
        except ValueError:
            continue
        if network.version == 4 and network.is_private and 22 <= network.prefixlen <= 30:
            candidates.append(str(network))
    normalized = []
    for value in candidates:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            continue
        if network.version == 4 and network.is_private and network.num_addresses <= 1024:
            text = str(network)
            if text not in normalized:
                normalized.append(text)
    return normalized


_ONVIF_PROBE = b'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>
<tds:GetCapabilities xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><tds:Category>All</tds:Category></tds:GetCapabilities>
</s:Body></s:Envelope>'''


async def _probe_camera_host(host: str, subnet: str, timeout: float, semaphore: asyncio.Semaphore) -> dict | None:
    ports = (80, 8000, 8080, 8899, 2020, 443)
    async with semaphore:
        for port in ports:
            writer = None
            try:
                tls = None
                if port == 443:
                    tls = ssl.create_default_context()
                    tls.check_hostname = False
                    tls.verify_mode = ssl.CERT_NONE
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=tls, server_hostname=host if tls else None), timeout=timeout,
                )
                request = (
                    f"POST /onvif/device_service HTTP/1.1\r\nHost: {host}:{port}\r\n"
                    "Content-Type: application/soap+xml; charset=utf-8\r\n"
                    f"Content-Length: {len(_ONVIF_PROBE)}\r\nConnection: close\r\n\r\n"
                ).encode() + _ONVIF_PROBE
                writer.write(request); await writer.drain()
                response = await asyncio.wait_for(reader.read(8192), timeout=max(timeout, 0.8))
                lower = response.lower()
                status = response.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                onvif_markers = (b"tds:", b"ter:", b"getcapabilitiesresponse", b"notauthorized", b"gsoap")
                status_code = status.split()[1] if len(status.split()) > 1 else ""
                has_onvif_payload = any(marker in lower for marker in onvif_markers)
                is_digest_challenge = status_code == "401" and b"digest" in lower
                if (status_code in {"200", "400", "500"} and has_onvif_payload) or is_digest_challenge:
                    scheme = "https" if port == 443 else "http"
                    return {"host": host, "xaddr": f"{scheme}://{host}:{port}/onvif/device_service",
                            "types": ["ONVIF routed probe"], "scopes": [], "source": "routed_scan",
                            "subnet": subnet, "onvif_port": port, "status": status}
            except (asyncio.TimeoutError, OSError, ssl.SSLError):
                pass
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
        for port in (554, 8554):
            writer = None
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
                writer.write(f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: Sentinel\r\n\r\n".encode())
                await writer.drain()
                response = await asyncio.wait_for(reader.read(1024), timeout=max(timeout, 0.8))
                if response.startswith(b"RTSP/"):
                    status = response.split(b"\r\n", 1)[0].decode("latin-1", "replace")
                    return {"host": host, "xaddr": None, "types": ["RTSP service"], "scopes": [],
                            "source": "routed_scan", "subnet": subnet, "rtsp_port": port,
                            "status": f"{status}; stream path still required"}
            except (asyncio.TimeoutError, OSError):
                pass
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
    return None


async def _scan_routed_subnets(subnets: list[str], timeout: float) -> list[dict]:
    semaphore = asyncio.Semaphore(64)
    tasks = []
    for value in subnets:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise CameraServiceError(f"Invalid camera subnet: {value}") from exc
        if not network.is_private or network.version != 4 or network.num_addresses > 1024:
            raise CameraServiceError(f"Camera subnet must be a private IPv4 network with 1024 addresses or fewer: {value}")
        tasks.extend(_probe_camera_host(str(host), str(network), min(timeout, 1.0), semaphore) for host in network.hosts())
    return [item for item in await asyncio.gather(*tasks) if item]


async def discover_onvif(timeout_seconds: float = 3, subnets: list[str] | None = None,
                         scan_routed_subnets: bool = True) -> dict:
    def run() -> list[dict]:
        try:
            from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
        except ImportError:
            return []
        discovery = WSDiscovery()
        discovery.start()
        try:
            services = discovery.searchServices(timeout=timeout_seconds)
            found = {}
            for service in services:
                for xaddr in service.getXAddrs() or []:
                    parsed = urllib.parse.urlsplit(xaddr)
                    if not parsed.hostname:
                        continue
                    try:
                        _private_host(parsed.hostname)
                    except CameraServiceError:
                        continue
                    found[parsed.hostname] = {"host": parsed.hostname, "xaddr": xaddr,
                                              "types": [str(x) for x in service.getTypes() or []],
                                              "scopes": [str(x) for x in service.getScopes() or []]}
            return list(found.values())
        finally:
            discovery.stop()
    multicast = await asyncio.to_thread(run)
    targets = list(subnets or [])
    if scan_routed_subnets:
        targets.extend(routed_private_subnets())
    targets = list(dict.fromkeys(targets))
    routed = await _scan_routed_subnets(targets, max(0.2, timeout_seconds / 5)) if targets else []
    merged = {item["host"]: item for item in routed}
    for item in multicast:
        item.setdefault("source", "multicast")
        merged[item["host"]] = item
    return {"cameras": list(merged.values()), "scanned_subnets": targets,
            "multicast_available": bool(multicast)}


async def onvif_profiles(host: str, port: int, username: str | None, password: str | None) -> list[dict]:
    _private_host(host)
    def run() -> list[dict]:
        try:
            from onvif import ONVIFCamera
        except ImportError as exc:
            raise CameraServiceError("ONVIF profile dependency is not installed.", 503) from exc
        camera = ONVIFCamera(host, port, username or "", password or "")
        media = camera.create_media_service()
        result = []
        for profile in media.GetProfiles():
            uri = media.GetStreamUri({"StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                                      "ProfileToken": profile.token}).Uri
            clean = validate_stream_url(uri, host)
            encoder = getattr(profile, "VideoEncoderConfiguration", None)
            resolution = getattr(encoder, "Resolution", None)
            result.append({"token": profile.token, "name": getattr(profile, "Name", profile.token),
                           "stream_url": clean, "width": getattr(resolution, "Width", None),
                           "height": getattr(resolution, "Height", None)})
        return result
    return await asyncio.to_thread(run)
