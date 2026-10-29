import asyncio
import json
import logging
import socket
import threading
from pathlib import Path
from typing import Any

from app import camera_db, camera_service, db, homekit_db, meross_service, nest_service, ring_service, smartthings_service, tuya_service, yale_service

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "homekit"
STATE_FILE = DATA_DIR / "accessory.state"

_driver = None
_thread: threading.Thread | None = None
_main_loop: asyncio.AbstractEventLoop | None = None
_last_error: str | None = None

TUYA_AC_BRANDS = {"tuya", "smartlife", "smart-life", "milexus"}
FAN_SPEED_PERCENT = {
    "mute": 12, "low": 25, "mid_low": 38, "mid": 50,
    "mid_high": 62, "high": 75, "strong": 100, "auto": 50,
}


def _fan_speed_name(percent: float) -> str:
    levels = ((12, "mute"), (25, "low"), (38, "mid_low"), (50, "mid"),
              (62, "mid_high"), (75, "high"), (100, "strong"))
    return min(levels, key=lambda item: abs(item[0] - float(percent)))[1]


def classify(device) -> tuple[str | None, str | None]:
    text = " ".join(str(value or "") for value in (device.name, device.model, device.device_type, device.brand)).lower()
    if device.brand.lower() in {"printer", "cudy"} or "router" in text or "printer" in text:
        return None, "This device type does not have a safe Apple Home profile yet."
    if device.brand.lower() == "ip-camera" or "camera" in text or device.brand.lower() == "ring":
        return "camera", None
    if device.brand.lower() == "yale" or "lock" in text:
        return "lock", None
    if "garage" in text:
        return "garage-door", None
    if device.brand.lower() == "nest" or "thermostat" in text:
        return "thermostat", None
    if any(kind in text for kind in ("climate", "air-conditioner", "air conditioner")):
        return "heater-cooler", None
    for needle, profile in (("motion", "motion-sensor"), ("contact", "contact-sensor"), ("smoke", "smoke-sensor"), ("carbon monoxide", "co-sensor"), ("water leak", "leak-sensor")):
        if needle in text:
            return profile, None
    if "light" in text or "lamp" in text or "dimmer" in text:
        return "light", None
    if any(word in text for word in ("plug", "outlet", "switch")) or device.brand.lower() in {"meross", "tuya", "milexus", "smartlife", "smart-life"}:
        return "outlet", None
    return None, "This device type does not have a safe Apple Home profile yet."


async def sync_accessory_rows() -> list[dict[str, Any]]:
    devices = await db.list_devices()
    for device in devices:
        profile, _ = classify(device)
        if profile:
            await homekit_db.ensure_accessory(device.id, profile)
    return await homekit_db.list_accessories()


async def read_state(device) -> dict[str, Any]:
    brand = device.brand.lower()
    if brand == "smartthings":
        return await smartthings_service.get_status(device, refresh_first=True)
    if brand == "nest":
        return await nest_service.get_status(device)
    if brand in TUYA_AC_BRANDS:
        return await tuya_service.get_state(device)
    if brand == "ring":
        return await ring_service.get_status(device)
    if brand == "yale":
        return await yale_service.get_status(device)
    return await meross_service.get_state(device)


async def write_value(device, profile: str, characteristic: str, value: Any) -> None:
    brand = device.brand.lower()
    if profile in {"outlet", "light"} and characteristic == "On":
        fn = smartthings_service.turn_on if value and brand == "smartthings" else smartthings_service.turn_off if brand == "smartthings" else tuya_service.turn_on if value and brand in {"tuya", "smartlife", "smart-life", "milexus"} else tuya_service.turn_off if brand in {"tuya", "smartlife", "smart-life", "milexus"} else meross_service.turn_on if value else meross_service.turn_off
        await fn(device)
        return
    if profile == "light" and characteristic == "Brightness":
        if brand == "smartthings":
            await smartthings_service.set_brightness(device, int(value))
        else:
            await meross_service.set_brightness(device, int(value))
        return
    if profile == "lock" and characteristic == "LockTargetState":
        await (yale_service.lock(device) if int(value) else yale_service.unlock(device))
        return
    if profile == "garage-door" and characteristic == "TargetDoorState":
        await (meross_service.garage_close(device) if int(value) else meross_service.garage_open(device))
        return
    if profile == "thermostat" and characteristic == "TargetHeatingCoolingState" and brand == "nest":
        await nest_service.set_mode(device, {0: "OFF", 1: "HEAT", 2: "COOL", 3: "HEATCOOL"}[int(value)])
        return
    if profile == "thermostat" and characteristic == "TargetTemperature" and brand == "nest":
        state = await nest_service.get_status(device)
        mode = str((state.get("appliance") or {}).get("mode") or "HEAT").upper()
        await (nest_service.set_cool(device, float(value)) if mode == "COOL" else nest_service.set_heat(device, float(value)))
        return
    if profile == "thermostat" and brand in TUYA_AC_BRANDS:
        if characteristic == "TargetHeatingCoolingState":
            target = int(value)
            if target == 0:
                await tuya_service.turn_off(device)
                return
            # Tuya ACs commonly call cooling "cold" and heating "hot".
            # Installations with different enum values can override these in
            # device_key JSON with a homekit_modes object.
            config = json.loads(device.device_key or "{}")
            modes = {"heat": "hot", "cool": "cold", "auto": "auto", **config.get("homekit_modes", {})}
            await tuya_service.set_values(device, {"power": True, "mode": modes[{1: "heat", 2: "cool", 3: "auto"}[target]]})
            return
        if characteristic == "TargetTemperature":
            await tuya_service.set_values(device, {"target_temperature": float(value)})
            return
        if characteristic == "Active":
            await (tuya_service.turn_on(device) if int(value) else tuya_service.turn_off(device))
            return
        if characteristic == "RotationSpeed":
            await tuya_service.set_values(device, {"fan_speed": _fan_speed_name(float(value))})
            return
        if characteristic == "SwingMode":
            await tuya_service.set_values(device, {"vertical_swing": "1" if int(value) else "0"})
            return
    if profile == "heater-cooler" and brand in TUYA_AC_BRANDS:
        if characteristic == "Active":
            await (tuya_service.turn_on(device) if int(value) else tuya_service.turn_off(device))
            return
        if characteristic == "TargetHeaterCoolerState":
            config = json.loads(device.device_key or "{}")
            modes = {"heat": "hot", "cool": "cold", "auto": "auto", **config.get("homekit_modes", {})}
            await tuya_service.set_values(device, {"power": True, "mode": modes[{0: "auto", 1: "heat", 2: "cool"}[int(value)]]})
            return
        if characteristic in {"CoolingThresholdTemperature", "HeatingThresholdTemperature"}:
            await tuya_service.set_values(device, {"target_temperature": float(value)})
            return
        if characteristic == "RotationSpeed":
            await tuya_service.set_values(device, {"fan_speed": _fan_speed_name(float(value))})
            return
        if characteristic == "SwingMode":
            await tuya_service.set_values(device, {"vertical_swing": "1" if int(value) else "0"})
            return
    raise RuntimeError(f"{profile} does not support writing {characteristic} yet.")


async def _write_temperature_display_units(row: dict[str, Any], value: Any) -> None:
    units = 1 if int(value) else 0
    await homekit_db.set_temperature_display_units(row["device_id"], units)
    row["temperature_display_units"] = units


def _run(coro, timeout: float = 15):
    if not _main_loop:
        raise RuntimeError("Sentinel event loop is unavailable.")
    return asyncio.run_coroutine_threadsafe(coro, _main_loop).result(timeout=timeout)


def _state_value(state: dict[str, Any], profile: str, characteristic: str):
    raw = state.get("raw") or {}
    appliance = state.get("appliance") or {}
    if characteristic in {"On", "OutletInUse"}:
        return bool(state.get("is_on"))
    if characteristic == "Brightness":
        return int(state.get("luminance") or 100)
    if characteristic in {"LockCurrentState", "LockTargetState"}:
        locked = raw.get("locked", state.get("is_on", False))
        return 1 if locked else 0
    if characteristic in {"CurrentDoorState", "TargetDoorState"}:
        return 0 if state.get("is_open") else 1
    if characteristic == "CurrentTemperature":
        return float(appliance.get("ambientCelsius") or appliance.get("ambient_temperature_celsius") or appliance.get("currentTemperature") or raw.get("temperature_celsius") or 20)
    if characteristic == "CurrentRelativeHumidity":
        return float(appliance.get("humidity") or appliance.get("humidity_percent") or raw.get("humidity_percent") or 0)
    if characteristic in {"CurrentHeatingCoolingState", "TargetHeatingCoolingState"}:
        if not state.get("is_on", True):
            return 0
        mode = str(appliance.get("mode") or "OFF").upper()
        mode = {"COLD": "COOL", "HOT": "HEAT"}.get(mode, mode)
        if characteristic == "CurrentHeatingCoolingState":
            hvac = str(appliance.get("hvacStatus") or mode).upper()
            return 1 if "HEAT" in hvac else 2 if "COOL" in hvac else 0
        return {"OFF": 0, "HEAT": 1, "COOL": 2, "HEATCOOL": 3}.get(mode, 0)
    if characteristic == "TargetTemperature":
        return float(appliance.get("heatCelsius") or appliance.get("coolCelsius") or appliance.get("targetTemperature") or 20)
    if characteristic == "TemperatureDisplayUnits":
        return 1 if str(appliance.get("temperatureScale") or "C").upper().startswith("F") else 0
    if characteristic == "Active":
        return 1 if state.get("is_on") else 0
    if characteristic == "RotationSpeed":
        return FAN_SPEED_PERCENT.get(str(appliance.get("fanSpeed") or "").lower(), 50)
    if characteristic == "SwingMode":
        return 0 if str(appliance.get("verticalSwing") or "0").lower() in {"0", "off", "false"} else 1
    if characteristic == "CurrentHeaterCoolerState":
        if not state.get("is_on"):
            return 0
        mode = str(appliance.get("mode") or "").lower()
        return 2 if mode in {"hot", "heat"} else 3 if mode in {"cold", "cool"} else 1
    if characteristic == "TargetHeaterCoolerState":
        mode = str(appliance.get("mode") or "").lower()
        return 1 if mode in {"hot", "heat"} else 2 if mode in {"cold", "cool"} else 0
    if characteristic in {"CoolingThresholdTemperature", "HeatingThresholdTemperature"}:
        return float(appliance.get("targetTemperature") or appliance.get("coolCelsius") or appliance.get("heatCelsius") or 20)
    if characteristic in {"ContactSensorState", "MotionDetected", "SmokeDetected", "CarbonMonoxideDetected", "LeakDetected"}:
        active = raw.get("active", raw.get("detected", raw.get("open", False)))
        return bool(active) if characteristic == "MotionDetected" else (1 if active else 0)
    return 0


def _make_accessory(driver, device, row):
    from pyhap.accessory import Accessory

    profile = row["profile"]
    accessory = Accessory(driver, device.name, aid=row["aid"])
    service_name = {
        "outlet": "Outlet", "light": "Lightbulb", "lock": "LockMechanism", "garage-door": "GarageDoorOpener",
        "thermostat": "Thermostat", "heater-cooler": "HeaterCooler", "motion-sensor": "MotionSensor", "contact-sensor": "ContactSensor",
        "smoke-sensor": "SmokeSensor", "co-sensor": "CarbonMonoxideSensor", "leak-sensor": "LeakSensor",
    }.get(profile)
    if not service_name:
        return None
    optional_characteristics = {
        "light": ["Brightness"],
        "thermostat": ["CurrentRelativeHumidity"],
        "heater-cooler": ["RotationSpeed", "SwingMode", "CoolingThresholdTemperature", "HeatingThresholdTemperature", "TemperatureDisplayUnits"],
    }.get(profile)
    service = accessory.add_preload_service(service_name, chars=optional_characteristics)
    characteristic_names = {
        "outlet": ("On", "OutletInUse"), "light": ("On", "Brightness"),
        "lock": ("LockCurrentState", "LockTargetState"), "garage-door": ("CurrentDoorState", "TargetDoorState"),
        "thermostat": ("CurrentHeatingCoolingState", "TargetHeatingCoolingState", "CurrentTemperature", "TargetTemperature", "TemperatureDisplayUnits", "CurrentRelativeHumidity"), "motion-sensor": ("MotionDetected",),
        "heater-cooler": ("Active", "CurrentHeaterCoolerState", "TargetHeaterCoolerState", "CurrentTemperature", "CoolingThresholdTemperature", "HeatingThresholdTemperature", "TemperatureDisplayUnits", "RotationSpeed", "SwingMode"),
        "contact-sensor": ("ContactSensorState",), "smoke-sensor": ("SmokeDetected",),
        "co-sensor": ("CarbonMonoxideDetected",), "leak-sensor": ("LeakDetected",),
    }[profile]
    writable = {"On", "Brightness", "LockTargetState", "TargetDoorState", "TargetHeatingCoolingState", "TargetTemperature", "Active", "TargetHeaterCoolerState", "CoolingThresholdTemperature", "HeatingThresholdTemperature", "RotationSpeed", "SwingMode"}
    for name in characteristic_names:
        if name == "TemperatureDisplayUnits":
            kwargs = {
                "getter_callback": lambda: int(row.get("temperature_display_units") or 0),
                "setter_callback": lambda value: _run(_write_temperature_display_units(row, value)),
            }
        else:
            kwargs = {"getter_callback": lambda n=name: _state_value(_run(read_state(device)), profile, n)}
        if name in writable and name != "TemperatureDisplayUnits":
            kwargs["setter_callback"] = lambda value, n=name: _run(write_value(device, profile, n, value))
        service.configure_char(name, **kwargs)
    return accessory


def _local_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _make_camera_accessory(driver, device, row):
    camera_profile = row.get("camera_profile")
    if not camera_profile or not camera_service.FFMPEG_PATH:
        return None
    from pyhap.camera import Camera, VIDEO_CODEC_PARAM_LEVEL_TYPES, VIDEO_CODEC_PARAM_PROFILE_ID_TYPES

    class SentinelCamera(Camera):
        def get_snapshot(self, image_size):
            return _run(camera_service.snapshot(camera_profile), timeout=20)

        async def start_stream(self, session_info, stream_config):
            source_url = camera_service._credential_url(camera_profile, substream=True)
            command = [
                camera_service.FFMPEG_PATH, "-hide_banner", "-loglevel", "warning", "-rtsp_transport", "tcp",
                "-i", source_url, "-an", "-map", "0:v:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "veryfast", "-tune", "zerolatency", "-r", str(stream_config["fps"]),
                "-vf", f"scale={stream_config['width']}:{stream_config['height']}",
                "-b:v", f"{stream_config['v_max_bitrate']}k", "-bufsize", f"{stream_config['v_max_bitrate']}k",
                "-payload_type", str(int.from_bytes(stream_config["v_payload_type"], "little")), "-ssrc", str(stream_config["v_ssrc"]),
                "-f", "rtp", "-srtp_out_suite", "AES_CM_128_HMAC_SHA1_80",
                "-srtp_out_params", stream_config["v_srtp_key"],
                f"srtp://{stream_config['address']}:{stream_config['v_port']}?rtcpport={stream_config['v_port']}&pkt_size=1378",
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, limit=1024
                )
            except OSError:
                logger.exception("Could not start HomeKit camera stream for %s.", device.name)
                return False
            session_info["process"] = process
            return True

    options = {
        "address": _local_address(), "srtp": True, "stream_count": 1,
        "video": {
            "codec": {
                "profiles": [VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"], VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"]],
                "levels": [VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"], VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_2"]],
            },
            "resolutions": [[1280, 720, 30], [640, 360, 30], [320, 180, 15]],
        },
        "audio": {"codecs": [{"type": "OPUS", "samplerate": 24}]},
    }
    return SentinelCamera(options, driver, device.name, aid=row["aid"])


def _make_ring_accessory(driver, device, row):
    from pyhap.accessory import Accessory

    class SentinelRingDoorbell(Accessory):
        def __init__(self):
            super().__init__(driver, device.name, aid=row["aid"])
            self.doorbell = self.add_preload_service("Doorbell")
            self.motion = self.add_preload_service("MotionSensor")
            self.event = self.doorbell.get_characteristic("ProgrammableSwitchEvent")
            self.motion_detected = self.motion.get_characteristic("MotionDetected")
            self.seen: set[str] = set()

        async def run(self):
            while not self.driver.aio_stop_event.is_set():
                delay = 5
                try:
                    payload = _run(ring_service.get_active_alerts(device), timeout=15)
                    alerts = payload.get("alerts", [])
                    active_ids = {str(alert.get("id")) for alert in alerts}
                    for alert in alerts:
                        event_id = str(alert.get("id"))
                        if event_id in self.seen:
                            continue
                        kind = str(alert.get("kind") or "").lower()
                        if "motion" in kind:
                            self.motion_detected.set_value(True)
                        else:
                            self.event.set_value(0)
                    self.motion_detected.set_value(any("motion" in str(alert.get("kind") or "").lower() for alert in alerts))
                    self.seen.update(active_ids)
                    if len(self.seen) > 200:
                        self.seen = active_ids
                except Exception:
                    delay = 30
                    logger.warning("Ring HomeKit event polling failed for %s.", device.name, exc_info=True)
                if await asyncio.to_thread(self.driver.stop_event.wait, delay):
                    break

    return SentinelRingDoorbell()


def _bridge_thread(settings: dict[str, Any], devices_by_id: dict[int, Any], rows: list[dict[str, Any]]) -> None:
    global _driver, _last_error
    try:
        from pyhap.accessory import Bridge
        from pyhap.accessory_driver import AccessoryDriver
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        driver = AccessoryDriver(port=settings["port"], persist_file=str(STATE_FILE))
        bridge = Bridge(driver, settings["bridge_name"])
        for row in rows:
            device = devices_by_id.get(row["device_id"])
            if not device or not row["enabled"] or not device.is_enabled:
                continue
            if row["profile"] == "camera" and device.brand.lower() == "ring":
                accessory = _make_ring_accessory(driver, device, row)
            elif row["profile"] == "camera":
                accessory = _make_camera_accessory(driver, device, row)
            else:
                accessory = _make_accessory(driver, device, row)
            if accessory:
                bridge.add_accessory(accessory)
        driver.add_accessory(accessory=bridge)
        _driver = driver
        _last_error = None
        driver.start()
    except Exception as exc:
        _last_error = str(exc)
        logger.exception("HomeKit bridge stopped unexpectedly.")
    finally:
        _driver = None


async def start() -> None:
    global _thread, _main_loop, _last_error
    if _thread and _thread.is_alive():
        return
    settings = await homekit_db.get_settings()
    if not settings["enabled"]:
        return
    _main_loop = asyncio.get_running_loop()
    rows = await sync_accessory_rows()
    devices = {device.id: device for device in await db.list_devices()}
    for row in rows:
        device = devices.get(row["device_id"])
        if row["profile"] != "camera" or not device:
            continue
        if device.brand.lower() == "ip-camera":
            row["camera_profile"] = await camera_db.get_camera_by_device(device.id, include_secrets=True)
            await homekit_db.set_error(device.id, None if row["camera_profile"] and camera_service.FFMPEG_PATH else "Camera profile or FFmpeg is unavailable.")
        else:
            await homekit_db.set_error(device.id, "Ring snapshots and events are available in Sentinel, but Ring live-video relay is not available in this bridge build.")
    _thread = threading.Thread(target=_bridge_thread, args=(settings, devices, rows), daemon=True, name="sentinel-homekit")
    _thread.start()


async def stop() -> None:
    global _thread
    driver = _driver
    if driver:
        driver.stop()
    if _thread and _thread.is_alive():
        await asyncio.to_thread(_thread.join, 8)
    _thread = None


async def restart() -> None:
    await stop()
    await start()


async def reset_pairing() -> None:
    await stop()
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    await start()


def _paired() -> bool:
    if _driver:
        return bool(_driver.state.paired)
    if not STATE_FILE.exists():
        return False
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return bool(data.get("paired_clients"))
    except (OSError, json.JSONDecodeError):
        return False


def pairing_details() -> dict[str, Any]:
    driver = _driver
    if not driver or _paired():
        return {"pin": None, "setup_uri": None}
    accessory = getattr(driver, "accessory", None)
    return {
        "pin": driver.state.pincode.decode(),
        "setup_uri": accessory.xhm_uri() if accessory else None,
    }


async def status() -> dict[str, Any]:
    settings = await homekit_db.get_settings()
    rows = await sync_accessory_rows()
    details = pairing_details()
    return {
        **settings,
        "running": bool(_thread and _thread.is_alive() and _driver),
        "paired": _paired(),
        "last_error": _last_error,
        "accessory_count": sum(1 for row in rows if row["enabled"] and row["device_enabled"]),
        "ffmpeg_available": bool(camera_service.FFMPEG_PATH),
        "hostname": socket.gethostname(),
        **details,
    }
