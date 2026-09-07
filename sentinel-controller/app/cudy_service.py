import asyncio
import hashlib
import html
import json
import os
import re
import time
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv

from app.models import Device


load_dotenv()

DEFAULT_TIMEOUT_SECONDS = float(os.getenv("CUDY_REQUEST_TIMEOUT_SECONDS", "5"))
USER_AGENT = "Sentinel/0.1"


class CudyServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class CudyMissingHostError(CudyServiceError):
    status_code = 400


class CudyAuthError(CudyServiceError):
    status_code = 401


class CudyCredentialsMissingError(CudyAuthError):
    pass


class CudyCredentialsRejectedError(CudyAuthError):
    pass


class CudyUnsupportedError(CudyServiceError):
    status_code = 422


class CudyTimeoutError(CudyServiceError):
    status_code = 504


def _base_url(device: Device) -> str:
    if not device.host:
        raise CudyMissingHostError("Cudy router host is missing.")
    host = device.host.strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return "http://" + host


def _config(device: Device) -> dict[str, Any]:
    if not device.device_key:
        return {"username": "root", "password": ""}
    value = device.device_key.strip()
    if not value:
        return {"username": "root", "password": ""}
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CudyUnsupportedError("Cudy device_key JSON is invalid.") from exc
        return {
            "username": parsed.get("username") or parsed.get("user") or "root",
            "password": parsed.get("password") or parsed.get("pass") or "",
        }
    return {"username": "root", "password": value}


def _urlopen_sync(req: request.Request, timeout_seconds: float) -> tuple[int, str]:
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except TimeoutError as exc:
        raise CudyTimeoutError("Timed out contacting Cudy router.") from exc
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
    except error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise CudyTimeoutError("Timed out contacting Cudy router.") from exc
        raise CudyServiceError(f"Could not reach Cudy router: {exc.reason}") from exc
    except OSError as exc:
        raise CudyServiceError(f"Could not reach Cudy router: {exc}") from exc


class _HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        data = dict(attrs)
        name = data.get("name")
        if name:
            self.values[name] = data.get("value") or ""


async def _http_json(url: str, payload: dict[str, Any], timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    status, response_body = await asyncio.to_thread(_urlopen_sync, req, timeout_seconds)
    if status >= 400:
        raise CudyServiceError(f"Cudy router returned HTTP {status}.")
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise CudyUnsupportedError("Cudy router returned non-JSON data.") from exc


async def _http_probe(url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[int, str]:
    req = request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    return await asyncio.to_thread(_urlopen_sync, req, timeout_seconds)


def _opener_read_sync(opener: request.OpenerDirector, req: request.Request, timeout_seconds: float) -> tuple[int, str]:
    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise CudyTimeoutError("Timed out contacting Cudy router.") from exc
    except error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise CudyTimeoutError("Timed out contacting Cudy router.") from exc
        raise CudyServiceError(f"Could not reach Cudy router: {exc.reason}") from exc
    except OSError as exc:
        raise CudyServiceError(f"Could not reach Cudy router: {exc}") from exc


def _luci_get_sync(
    opener: request.OpenerDirector,
    url: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    req = request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    return _opener_read_sync(opener, req, timeout_seconds)


def _luci_post_sync(
    opener: request.OpenerDirector,
    url: str,
    payload: dict[str, str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
        method="POST",
    )
    return _opener_read_sync(opener, req, timeout_seconds)


def _luci_login_opener_sync(device: Device, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, request.OpenerDirector]:
    cfg = _config(device)
    if not cfg["password"]:
        raise CudyCredentialsMissingError("Cudy admin password is required for management actions.")

    base_url = _base_url(device)
    opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
    _, login_page = _luci_get_sync(opener, base_url + "/cgi-bin/luci/", timeout_seconds)
    hidden_parser = _HiddenInputParser()
    hidden_parser.feed(login_page)
    hidden = hidden_parser.values
    salt = hidden.get("salt", "")
    token = hidden.get("token", "")
    if not salt:
        raise CudyUnsupportedError("Cudy LuCI login page did not include the expected password salt.")

    password_hash = hashlib.sha256((cfg["password"] + salt).encode("utf-8")).hexdigest()
    if token:
        password_hash = hashlib.sha256((password_hash + token).encode("utf-8")).hexdigest()

    _, login_response = _luci_post_sync(
        opener,
        base_url + "/cgi-bin/luci/",
        {
            **hidden,
            "luci_username": cfg["username"],
            "luci_password": password_hash,
            "luci_language": "auto",
            "zonename": "",
            "timeclock": str(int(time.time())),
        },
        timeout_seconds,
    )
    if "cbi-modal-auth" in login_response:
        raise CudyCredentialsRejectedError("Cudy router rejected the saved admin credentials.")
    return base_url, opener


def _luci_status_sync(device: Device, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    base_url, opener = _luci_login_opener_sync(device, timeout_seconds)

    status_pages: dict[str, str] = {}
    for key, path in {
        "system": "/cgi-bin/luci/admin/system/status",
        "wan": "/cgi-bin/luci/admin/network/wan/status",
        "devices": "/cgi-bin/luci/admin/network/devices/status",
        "bandwidth": "/cgi-bin/luci/admin/status/bandwidth?iface=eth0",
        "mesh": "/cgi-bin/luci/admin/network/mesh/status",
        "mesh_clients": "/cgi-bin/luci/admin/network/mesh/clients",
    }.items():
        status, body = _luci_get_sync(opener, base_url + path, timeout_seconds)
        if status >= 400:
            raise CudyServiceError(f"Cudy LuCI status endpoint returned HTTP {status}.")
        status_pages[key] = body

    system_table = _extract_luci_table(status_pages["system"])
    wan_table = _extract_luci_table(status_pages["wan"])
    devices_table = _extract_luci_table(status_pages["devices"])
    bandwidth = _extract_luci_bandwidth(status_pages["bandwidth"])
    mesh_table = _extract_luci_table(status_pages["mesh"])
    mesh_nodes = _extract_luci_mesh_clients(status_pages["mesh_clients"], device.host)

    firmware = system_table.get("Firmware Version") or device.model or "Cudy router"
    protocol = wan_table.get("Protocol")
    wan_ip = wan_table.get("IP Address")
    clients = devices_table.get("Devices")
    mesh_units = mesh_table.get("Mesh Units") or str(len(mesh_nodes) or "")

    return {
        "is_on": True,
        "appliance": {
            "type": "router",
            "title": "Router stats",
            "status": wan_table.get("Status") or "Online",
            "model": firmware,
            "uptime": system_table.get("Uptime") or "--",
            "download": bandwidth.get("download"),
            "upload": bandwidth.get("upload"),
            "totalDownload": bandwidth.get("totalDownload"),
            "totalUpload": bandwidth.get("totalUpload"),
            "traffic": _format_traffic_summary(bandwidth),
            "wan": wan_ip or protocol or "--",
            "clients": clients or "--",
            "meshUnits": mesh_units,
            "meshNodes": mesh_nodes,
        },
        "raw": {
            "source": "luci",
            "system": system_table,
            "wan": wan_table,
            "devices": devices_table,
            "bandwidth": bandwidth,
            "mesh": mesh_table,
        },
    }


async def _luci_status(device: Device) -> dict[str, Any]:
    return await asyncio.to_thread(_luci_status_sync, device)


async def _ubus_call(device: Device, object_name: str, method: str, params: dict[str, Any] | None = None) -> Any:
    cfg = _config(device)
    if not cfg["password"]:
        raise CudyCredentialsMissingError("Cudy admin password is required for management actions.")

    url = _base_url(device) + "/ubus"
    login = await _http_json(
        url,
        {
            "jsonrpc": "2.0",
            "id": int(time.time()),
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": cfg["username"], "password": cfg["password"]},
            ],
        },
    )
    result = login.get("result")
    if not isinstance(result, list) or result[0] != 0:
        raise CudyCredentialsRejectedError("Cudy router rejected the saved admin credentials.")
    session_id = (result[1] or {}).get("ubus_rpc_session")
    if not session_id:
        raise CudyCredentialsRejectedError("Cudy router did not return a management session for the saved credentials.")

    response = await _http_json(
        url,
        {
            "jsonrpc": "2.0",
            "id": int(time.time()),
            "method": "call",
            "params": [session_id, object_name, method, params or {}],
        },
    )
    call_result = response.get("result")
    if not isinstance(call_result, list) or call_result[0] != 0:
        raise CudyServiceError(f"Cudy management call failed for {object_name}.{method}.")
    return call_result[1] if len(call_result) > 1 else {}


async def get_status(device: Device) -> dict[str, Any]:
    try:
        board = await _ubus_call(device, "system", "board")
        info = await _ubus_call(device, "system", "info")
        interfaces = await _ubus_call(device, "network.interface", "dump")
        wan = _find_wan_interface(interfaces)
        appliance = _stats_appliance(board, info, wan)
        return {"is_on": True, "appliance": appliance, "raw": {"board": board, "info": info, "interfaces": interfaces}}
    except CudyServiceError as exc:
        try:
            state = await _luci_status(device)
            state["raw"]["ubus_error"] = exc.message
            return state
        except CudyServiceError as luci_exc:
            if not isinstance(exc, CudyCredentialsRejectedError):
                exc = luci_exc

        status, body = await _http_probe(_base_url(device))
        reachable = status < 500
        management_label = _management_status_label(exc)
        return {
            "is_on": reachable,
            "appliance": {
                "type": "router",
                "title": "Router status",
                "status": "Reachable" if reachable else "Unavailable",
                "model": device.model or "Cudy router",
                "wan": management_label,
                "uptime": management_label,
                "clients": "Open details",
            },
            "raw": {"http_status": status, "body_preview": body[:180], "management_error": exc.message},
    }


def _luci_reboot_sync(device: Device, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    base_url, opener = _luci_login_opener_sync(device, timeout_seconds)
    status, body = _luci_get_sync(opener, base_url + "/cgi-bin/luci/admin/system/reboot/apply", timeout_seconds)
    if status >= 400:
        raise CudyServiceError(f"Cudy LuCI reboot endpoint returned HTTP {status}.")
    if "cbi-modal-auth" in body:
        raise CudyCredentialsRejectedError("Cudy router rejected the saved admin credentials.")
    return {
        "is_on": False,
        "message": f"{device.name} reboot command sent through LuCI.",
        "raw": {"source": "luci", "http_status": status},
    }


async def _luci_reboot(device: Device) -> dict[str, Any]:
    return await asyncio.to_thread(_luci_reboot_sync, device)


def _luci_mesh_clients_sync(device: Device, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    base_url, opener = _luci_login_opener_sync(device, timeout_seconds)
    status, body = _luci_get_sync(opener, base_url + "/cgi-bin/luci/admin/network/mesh/clients", timeout_seconds)
    if status >= 400:
        raise CudyServiceError(f"Cudy LuCI mesh clients endpoint returned HTTP {status}.")
    return _extract_luci_mesh_clients(body, device.host)


def _luci_mesh_reboot_sync(
    device: Device,
    client_id: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    base_url, opener = _luci_login_opener_sync(device, timeout_seconds)
    encoded_client = parse.quote(client_id, safe="")
    reboot_url = base_url + f"/cgi-bin/luci/admin/network/mesh/reboot?client={encoded_client}"
    status, form_body = _luci_get_sync(opener, reboot_url, timeout_seconds)
    if status >= 400:
        raise CudyServiceError(f"Cudy mesh reboot form returned HTTP {status}.")
    if "cbi-modal-auth" in form_body:
        raise CudyCredentialsRejectedError("Cudy router rejected the saved admin credentials.")

    form_parser = _HiddenInputParser()
    form_parser.feed(form_body)
    payload = {
        **form_parser.values,
        "timeclock": str(int(time.time())),
        "cbi.apply": "1",
        "cbid.reboot.1.client": client_id,
    }
    status, response_body = _luci_post_sync(opener, reboot_url, payload, timeout_seconds)
    if status >= 400:
        raise CudyServiceError(f"Cudy mesh reboot endpoint returned HTTP {status}.")
    if "cbi-modal-auth" in response_body:
        raise CudyCredentialsRejectedError("Cudy router rejected the saved admin credentials.")
    return {"is_on": False, "raw": {"source": "luci", "http_status": status, "client_id": client_id}}


async def _luci_mesh_reboot(device: Device, client_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_luci_mesh_reboot_sync, device, client_id)


async def get_stats(device: Device) -> dict[str, Any]:
    return await get_status(device)


async def reboot(device: Device, target: str = "main") -> dict[str, Any]:
    if target not in {"main", "satellites", "all"}:
        raise CudyUnsupportedError("Unsupported Cudy reboot target.")

    if target == "main":
        try:
            await _ubus_call(device, "system", "reboot")
            return {"is_on": False, "message": f"{device.name} reboot command sent."}
        except CudyServiceError:
            return await _luci_reboot(device)

    mesh_nodes = await asyncio.to_thread(_luci_mesh_clients_sync, device)
    satellite_nodes = [node for node in mesh_nodes if not node.get("isMain")]
    if not satellite_nodes:
        raise CudyUnsupportedError("No Cudy mesh satellites were found to reboot.")

    rebooted: list[str] = []
    for node in satellite_nodes:
        await _luci_mesh_reboot(device, node["id"])
        rebooted.append(node.get("name") or node["id"])

    if target == "all":
        await _luci_mesh_reboot(device, _main_mesh_client_id(mesh_nodes))
        rebooted.append("main router")

    return {
        "is_on": False,
        "message": "Reboot command sent to " + ", ".join(rebooted) + ".",
        "raw": {"source": "luci", "target": target, "nodes": rebooted},
    }


async def test_reboot_path(device: Device) -> dict[str, Any]:
    base_url, opener = await asyncio.to_thread(_luci_login_opener_sync, device)
    status, body = await asyncio.to_thread(
        _luci_get_sync,
        opener,
        base_url + "/cgi-bin/luci/admin/system/reboot",
        DEFAULT_TIMEOUT_SECONDS,
    )
    if status >= 400:
        raise CudyServiceError(f"Cudy LuCI reboot confirmation endpoint returned HTTP {status}.")
    if "system/reboot/apply" not in body:
        raise CudyUnsupportedError("Cudy LuCI reboot confirmation page did not expose the apply endpoint.")
    return {"status": "ok", "source": "luci"}


def _read_response_bytes(response: Any) -> int:
    byte_count = 0
    while True:
        chunk = response.read(1024 * 128)
        if not chunk:
            break
        byte_count += len(chunk)
    return byte_count


def _speedtest_request_sync(
    url: str,
    method: str,
    body: bytes | None,
    timeout_seconds: float,
) -> tuple[int, float, int]:
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/octet-stream", "User-Agent": USER_AGENT},
        method=method,
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            byte_count = _read_response_bytes(response)
            elapsed = max(time.perf_counter() - started, 0.001)
            return response.status, elapsed, byte_count
    except TimeoutError as exc:
        raise CudyTimeoutError("Timed out running speed test.") from exc
    except error.HTTPError as exc:
        _read_response_bytes(exc)
        raise CudyServiceError(f"Speed test returned HTTP {exc.code}.") from exc
    except error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise CudyTimeoutError("Timed out running speed test.") from exc
        raise CudyServiceError(f"Speed test failed: {exc.reason}") from exc
    except OSError as exc:
        raise CudyServiceError(f"Speed test failed: {exc}") from exc


def _speedtest_sync() -> dict[str, Any]:
    timeout_seconds = float(os.getenv("SENTINEL_SPEEDTEST_TIMEOUT_SECONDS", "20"))
    download_size = int(os.getenv("SENTINEL_SPEEDTEST_DOWNLOAD_BYTES", "25000000"))
    upload_size = int(os.getenv("SENTINEL_SPEEDTEST_UPLOAD_BYTES", "10000000"))
    download_size = max(100_000, min(download_size, 200_000_000))
    upload_size = max(100_000, min(upload_size, 100_000_000))

    latency_status, latency_elapsed, _ = _speedtest_request_sync(
        "https://speed.cloudflare.com/__down?bytes=0",
        "GET",
        None,
        timeout_seconds,
    )
    if latency_status >= 400:
        raise CudyServiceError(f"Speed test latency probe returned HTTP {latency_status}.")

    download_status, download_elapsed, downloaded_bytes = _speedtest_request_sync(
        "https://speed.cloudflare.com/__down?bytes=" + str(download_size),
        "GET",
        None,
        timeout_seconds,
    )
    if download_status >= 400:
        raise CudyServiceError(f"Speed test download probe returned HTTP {download_status}.")

    upload_status, upload_elapsed, _ = _speedtest_request_sync(
        "https://speed.cloudflare.com/__up",
        "POST",
        b"0" * upload_size,
        timeout_seconds,
    )
    if upload_status >= 400:
        raise CudyServiceError(f"Speed test upload probe returned HTTP {upload_status}.")

    download_bytes_per_second = downloaded_bytes / max(download_elapsed, 0.001)
    upload_bytes_per_second = upload_size / max(upload_elapsed, 0.001)
    return {
        "source": "cloudflare",
        "latencyMs": round(latency_elapsed * 1000),
        "download": _format_bits_per_second(download_bytes_per_second),
        "upload": _format_bits_per_second(upload_bytes_per_second),
        "downloadBps": round(download_bytes_per_second * 8),
        "uploadBps": round(upload_bytes_per_second * 8),
        "downloadBytes": downloaded_bytes,
        "uploadBytes": upload_size,
        "downloadSize": _format_bytes(downloaded_bytes),
        "uploadSize": _format_bytes(upload_size),
    }


async def run_speedtest() -> dict[str, Any]:
    return await asyncio.to_thread(_speedtest_sync)


def _find_wan_interface(interfaces: dict[str, Any]) -> dict[str, Any]:
    for item in interfaces.get("interface", []):
        if item.get("interface") == "wan":
            return item
    return {}


def _stats_appliance(board: dict[str, Any], info: dict[str, Any], wan: dict[str, Any]) -> dict[str, Any]:
    memory = info.get("memory") or {}
    total_memory = memory.get("total")
    free_memory = memory.get("free")
    memory_text = "--"
    if total_memory and free_memory is not None:
        used_percent = round(((total_memory - free_memory) / total_memory) * 100)
        memory_text = f"{used_percent}% used"

    load = info.get("load") or []
    load_text = ", ".join(str(round(value / 65535, 2)) for value in load[:3]) if load else "--"
    ipv4 = ", ".join(item.get("address", "") for item in wan.get("ipv4-address", []) if item.get("address"))

    return {
        "type": "router",
        "title": "Router stats",
        "status": "Online",
        "model": board.get("model") or board.get("board_name") or "--",
        "uptime": _format_duration(info.get("uptime")),
        "load": load_text,
        "memory": memory_text,
        "download": None,
        "upload": None,
        "totalDownload": None,
        "totalUpload": None,
        "traffic": None,
        "wan": ipv4 or wan.get("proto") or "--",
        "clients": str(len(wan.get("route") or [])),
    }


def _extract_luci_table(markup: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    header_match = re.search(
        r"<th[^>]*>(.*?)</th>\s*<th[^>]*>(.*?)</th>",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if header_match:
        key = _clean_luci_text(header_match.group(1))
        value = _clean_luci_text(header_match.group(2))
        if key:
            rows[key] = value

    for match in re.finditer(
        r'id="cbi-table-\d+-content".*?<p[^>]*>(.*?)</p>.*?id="cbi-table-\d+-data".*?<p[^>]*>(.*?)</p>',
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        key = _clean_luci_text(match.group(1))
        value = _clean_luci_text(match.group(2))
        if key and key not in rows:
            rows[key] = value
    return rows


def _extract_luci_bandwidth(payload: str) -> dict[str, Any]:
    try:
        samples = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    if not isinstance(samples, list) or len(samples) < 2:
        return {}

    latest_pair = None
    for previous, current in zip(samples, samples[1:]):
        if not isinstance(previous, list) or not isinstance(current, list):
            continue
        if len(previous) < 4 or len(current) < 4:
            continue
        try:
            time_delta = float(current[0]) - float(previous[0])
            rx_delta = float(current[1]) - float(previous[1])
            tx_delta = float(current[3]) - float(previous[3])
        except (TypeError, ValueError):
            continue
        if time_delta <= 0 or rx_delta < 0 or tx_delta < 0:
            continue
        latest_pair = (rx_delta * 1_000_000 / time_delta, tx_delta * 1_000_000 / time_delta)

    latest_sample = None
    for sample in reversed(samples):
        if isinstance(sample, list) and len(sample) >= 4:
            latest_sample = sample
            break

    if latest_pair is None:
        return {}
    download_bytes, upload_bytes = latest_pair
    result = {
        "download": _format_bits_per_second(download_bytes),
        "upload": _format_bits_per_second(upload_bytes),
        "download_bps": round(download_bytes * 8),
        "upload_bps": round(upload_bytes * 8),
    }
    if latest_sample:
        try:
            result["totalDownload"] = _format_bytes(float(latest_sample[1]))
            result["totalUpload"] = _format_bytes(float(latest_sample[3]))
            result["totalDownloadBytes"] = round(float(latest_sample[1]))
            result["totalUploadBytes"] = round(float(latest_sample[3]))
        except (TypeError, ValueError):
            pass
    return result


def _format_bits_per_second(bytes_per_second: float) -> str:
    bits_per_second = max(0, bytes_per_second * 8)
    if bits_per_second >= 1_000_000:
        return f"{bits_per_second / 1_000_000:.2f} Mbps"
    if bits_per_second >= 1_000:
        return f"{bits_per_second / 1_000:.1f} Kbps"
    return f"{round(bits_per_second)} bps"


def _format_bytes(byte_count: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = max(0.0, byte_count)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{round(value)} {unit}"
    return f"{value:.2f} {unit}"


def _format_traffic_summary(bandwidth: dict[str, Any]) -> str | None:
    download = bandwidth.get("download")
    upload = bandwidth.get("upload")
    if download and upload:
        return f"Down {download} / Up {upload}"
    return None


def _extract_luci_mesh_clients(payload: str, main_host: str) -> list[dict[str, Any]]:
    try:
        clients = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(clients, list):
        return []

    normalized_main_host = _normalize_host(main_host)
    nodes: list[dict[str, Any]] = []
    for client in clients:
        if not isinstance(client, dict):
            continue
        sysreport = client.get("sysreport") if isinstance(client.get("sysreport"), dict) else {}
        ip_address = sysreport.get("ipaddr") or client.get("ipaddr")
        node_id = str(client.get("id") or sysreport.get("macaddr") or "")
        if not node_id:
            continue
        is_main = node_id == "000000000000" or _normalize_host(ip_address) == normalized_main_host
        nodes.append(
            {
                "id": node_id,
                "name": client.get("name") or sysreport.get("board") or node_id,
                "ip": ip_address,
                "mac": sysreport.get("macaddr"),
                "model": sysreport.get("board") or sysreport.get("hardware") or sysreport.get("model"),
                "firmware": sysreport.get("firmware"),
                "state": client.get("state") or ("connected" if is_main else "unknown"),
                "isMain": is_main,
                "parent": sysreport.get("parent"),
            }
        )
    return nodes


def _main_mesh_client_id(nodes: list[dict[str, Any]]) -> str:
    for node in nodes:
        if node.get("isMain"):
            return str(node["id"])
    return "000000000000"


def _normalize_host(value: Any) -> str:
    return str(value or "").strip().lower().replace("http://", "").replace("https://", "").rstrip("/")


def _clean_luci_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _management_status_label(exc: CudyServiceError) -> str:
    if isinstance(exc, CudyCredentialsMissingError):
        return "Credentials needed"
    if isinstance(exc, CudyCredentialsRejectedError):
        return "Credentials rejected"
    return "Management unavailable"


def _format_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "--"
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
