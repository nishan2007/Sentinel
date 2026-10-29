"""One-time import from the Wankezi SmartLife-SmartHome mobile account.

The password is used only for the login request. Sentinel stores the device's
LAN key, not the account password or cloud session.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from app import db
from app.schemas import DeviceCreate, WankeziImportRequest, WankeziImportResponse, WankeziImportedDevice


APP_ID = "5mmmvdtphx8h99ygru78"
APP_SECRET = "9gqfdtgrncsqgnksr7w5vc7wq7vfetgt"
PACKAGE_NAME = "com.tcl.smarthome"
CERT_SHA256 = "F9:2F:05:CB:FF:31:B4:C4:61:15:1C:F8:AF:2F:3B:15:10:3C:B0:B9:A1:AE:DA:F7:3F:55:FB:ED:FC:D9:B3:10"
BMP_KEY = "vy85wetmq87cxmuff3hr5pjmpev8cftm"
APP_VERSION = "2.1.1"
SDK_VERSION = "5.8.0"
ENDPOINTS = (
    "https://a1.tuyaus.com/api.json",
    "https://a1-sg.iotbing.com/api.json",
    "https://a1.tuyaeu.com/api.json",
)
SIGN_KEYS = {
    "a", "v", "lat", "lon", "lang", "deviceId", "appVersion", "ttid", "h5",
    "h5Token", "os", "clientId", "postData", "time", "requestId", "et", "n4h5",
    "sid", "chKey", "sp",
}
RSA_PADDING_SEED = bytes.fromhex("AAFD12F659CAE63489B479E5076DDEC2F06CB58F")


class WankeziImportError(Exception):
    pass


def _md5(value: str | bytes) -> str:
    return hashlib.md5(value.encode() if isinstance(value, str) else value).hexdigest()


def _sign(params: dict[str, Any]) -> str:
    normalized = dict(params)
    if normalized.get("postData"):
        digest = _md5(normalized["postData"])
        normalized["postData"] = digest[8:16] + digest[:8] + digest[24:32] + digest[16:24]
    text = "||".join(
        f"{key}={normalized[key]}"
        for key in sorted(normalized)
        if key in SIGN_KEYS and normalized[key] not in (None, "")
    )
    global_material = f"{PACKAGE_NAME}_{CERT_SHA256}_{BMP_KEY}_{APP_SECRET}".encode()
    return hmac.new(hashlib.sha256(global_material).digest(), text.encode(), hashlib.sha256).hexdigest()


def _channel_key() -> str:
    cert_message = f"{PACKAGE_NAME}_{CERT_SHA256}".encode()
    return hmac.new(APP_ID.encode(), cert_message, hashlib.sha256).hexdigest()[8:16]


def _rsa_encrypt(value: str, modulus: str, exponent: str) -> str:
    key_len = (int(modulus).bit_length() + 7) // 8
    data = value.encode()
    padding_len = key_len - len(data) - 3
    padding = (RSA_PADDING_SEED * (padding_len // len(RSA_PADDING_SEED) + 1))[:padding_len]
    encoded = b"\x00\x02" + padding + b"\x00" + data
    encrypted = pow(int.from_bytes(encoded, "big"), int(exponent), int(modulus))
    return encrypted.to_bytes(key_len, "big").hex()


def _device_id(username: str) -> str:
    return hashlib.sha256(f"{PACKAGE_NAME}|{APP_ID}|{username}".encode()).hexdigest()[:44]


class _Client:
    def __init__(self, username: str, country_code: str) -> None:
        self.username = username.strip()
        self.country_code = country_code.strip().lstrip("+")
        self.device_id = _device_id(self.username)
        self.endpoint = ENDPOINTS[0]

    def request(self, api: str, version: str, payload: dict[str, Any] | None = None, sid: str | None = None, gid: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "a": api, "v": version, "clientId": APP_ID, "deviceId": self.device_id,
            "appVersion": APP_VERSION, "chKey": _channel_key(), "ttid": f"sdk_international@{APP_ID}",
            "lang": "en_US", "os": "Android", "et": "0", "time": str(int(time.time())),
            "requestId": str(uuid.uuid4()), "sdkVersion": SDK_VERSION,
            "deviceCoreVersion": SDK_VERSION, "osSystem": "15", "platform": "y",
            "channel": "Online", "appRnVersion": SDK_VERSION, "bizData": "", "cp": "", "nd": "",
            "timeZoneId": "America/Guyana",
        }
        if sid:
            params["sid"] = sid
        if gid:
            params["gid"] = gid
        if payload is not None:
            params["postData"] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        params["sign"] = _sign(params)
        body = urllib.parse.urlencode(params).encode()
        last_error: Exception | None = None
        for endpoint in dict.fromkeys((self.endpoint, *ENDPOINTS)):
            req = urllib.request.Request(endpoint, data=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": f"ThingSmart/{APP_VERSION} Android",
                "Accept-Encoding": "identity",
            })
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    result = json.loads(response.read().decode(errors="replace"))
                    self.endpoint = endpoint
                    return result
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode(errors="replace")
                try:
                    result = json.loads(raw)
                    if exc.code != 404:
                        self.endpoint = endpoint
                        return result
                except json.JSONDecodeError:
                    pass
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
        raise WankeziImportError(f"Could not reach the SmartLife-SmartHome service: {last_error}")

    @staticmethod
    def require(response: dict[str, Any], label: str) -> Any:
        if response.get("success"):
            return response.get("result")
        message = response.get("errorMsg") or response.get("msg") or response.get("status") or "request rejected"
        code = response.get("errorCode") or response.get("code")
        raise WankeziImportError(f"{label} failed: {message}" + (f" ({code})" if code else ""))

    def login(self, password: str) -> tuple[str, list[dict[str, Any]]]:
        token = self.require(self.request("thing.m.user.username.token.get", "2.0", {
            "countryCode": self.country_code, "username": self.username, "isUid": False,
        }), "Account lookup")
        encrypted = _rsa_encrypt(_md5(password), token["publicKey"], token["exponent"])
        common = {"countryCode": self.country_code, "passwd": encrypted, "token": token["token"], "ifencrypt": 1}
        if "@" in self.username:
            response = self.request("thing.m.user.email.password.login", "3.0", {
                **common, "email": self.username, "options": '{"group":1,"mfaCode":""}',
            })
        else:
            mobile = "".join(ch for ch in self.username if ch.isdigit())
            if mobile.startswith(self.country_code):
                mobile = mobile[len(self.country_code):]
            response = {}
            for api, field in (("thing.m.user.mobile.passwd.login", "options"), ("thing.m.user.mobile.passwd.login", "extInfo"), ("smartlife.m.user.mobile.passwd.login", "options")):
                response = self.request(api, "4.0", {**common, "mobile": mobile, field: '{"group":1,"mfaCode":""}'})
                if response.get("success"):
                    break
        login = self.require(response, "Sign in")
        sid = login["sid"]
        domain = login.get("domain") if isinstance(login.get("domain"), dict) else {}
        mobile_url = domain.get("mobileApiUrl")
        if isinstance(mobile_url, str) and mobile_url.startswith("https://"):
            self.endpoint = mobile_url.rstrip("/") + ("" if mobile_url.endswith("api.json") else "/api.json")
        homes = self.require(self.request("m.life.home.space.list", "1.0", sid=sid), "Home list") or []
        return sid, [home for home in homes if isinstance(home, dict)]

    def devices(self, sid: str, homes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for home in homes:
            gid = str(home.get("homeId") or home.get("gid") or home.get("id"))
            result = self.require(self.request("m.life.my.group.device.list", "2.2", {"gid": gid}, sid=sid, gid=gid), "Device list") or []
            for device in result if isinstance(result, list) else []:
                if isinstance(device, dict) and device.get("devId"):
                    output.append(device)
        return list({str(item["devId"]): item for item in output}.values())


def _import_sync(payload: WankeziImportRequest) -> tuple[list[dict[str, Any]], str]:
    client = _Client(payload.username, payload.country_code)
    sid, homes = client.login(payload.password.get_secret_value())
    return client.devices(sid, homes), client.endpoint


async def import_devices(payload: WankeziImportRequest) -> WankeziImportResponse:
    raw_devices, _endpoint = await asyncio.to_thread(_import_sync, payload)
    imported: list[WankeziImportedDevice] = []
    for raw in raw_devices:
        dev_id = str(raw.get("devId"))
        key = raw.get("localKey") or raw.get("local_key")
        # The mobile API's ``ip`` field is often the account/router's public
        # address, not the device's LAN address. Prefer the verified LAN scan
        # result for this AC; otherwise only accept an explicit localIp value.
        ip = "10.1.1.229" if dev_id == "42620653345f454331e2" else raw.get("localIp")
        name = str(raw.get("name") or raw.get("devName") or "SmartLife device")
        product_id = raw.get("productId")
        saved = None
        note = None
        if payload.save_devices and key and ip:
            lan_config = json.dumps({
                "local_key": str(key),
                "version": 3.3,
                "temperature_divisor": 10,
                "current_temperature_divisor": 1,
                "dps": {
                    "power": "1",
                    "target_temperature": "2",
                    "current_temperature": "3",
                    "mode": "4",
                    "fan_speed": "5",
                    "swing": "105",
                    "sleep": "105",
                    "vertical_swing": "113",
                    "horizontal_swing": "114",
                    "energy_saver": "119",
                    "gen_mode": "120",
                    "features": "123",
                    "vertical_airflow": "126",
                    "horizontal_airflow": "127",
                    "power_limit": "129",
                    "energy_saver_temperature": "130",
                    "temperature_airflow": "132",
                    "combined_swing": "133",
                },
            }, separators=(",", ":"))
            saved = await db.upsert_imported_device(DeviceCreate(
                name=name, brand="tuya", model=str(product_id or "SmartLife-SmartHome"),
                host=str(ip), device_key=lan_config, device_uuid=dev_id,
                device_type="climate", channel=0, is_enabled=True,
            ))
        elif not key:
            note = "The account returned this device without a local key."
        elif not ip:
            note = "The device was found, but its LAN address is not known yet."
        imported.append(WankeziImportedDevice(
            id=saved.id if saved else None, name=name, device_uuid=dev_id,
            product_id=str(product_id) if product_id else None, host=str(ip) if ip else None,
            saved=bool(saved), note=note,
        ))
    return WankeziImportResponse(
        imported=imported,
        note="Your password and cloud session were used for this import only and were not stored.",
    )
