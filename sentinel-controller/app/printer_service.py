import asyncio
import ipaddress
import json
import os
import re
import socket
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from app import camera_service, discovery
from app.models import Device


load_dotenv()

DEFAULT_COMMUNITY = os.getenv("PRINTER_SNMP_COMMUNITY", "public")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("PRINTER_SNMP_TIMEOUT_SECONDS", "3"))
DEFAULT_RETRIES = int(os.getenv("PRINTER_SNMP_RETRIES", "0"))

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SERIAL_TABLE = "1.3.6.1.2.1.43.5.1.1.17"
OID_SUPPLY_DESC = "1.3.6.1.2.1.43.11.1.1.6"
OID_SUPPLY_UNIT = "1.3.6.1.2.1.43.11.1.1.7"
OID_SUPPLY_MAX = "1.3.6.1.2.1.43.11.1.1.8"
OID_SUPPLY_LEVEL = "1.3.6.1.2.1.43.11.1.1.9"
OID_INPUT_NAME = "1.3.6.1.2.1.43.8.2.1.13"
OID_INPUT_DESC = "1.3.6.1.2.1.43.8.2.1.18"
OID_INPUT_LEVEL = "1.3.6.1.2.1.43.8.2.1.10"
OID_INPUT_MAX = "1.3.6.1.2.1.43.8.2.1.9"
OID_INPUT_STATUS = "1.3.6.1.2.1.43.8.2.1.11"
OID_ALERT_SEVERITY = "1.3.6.1.2.1.43.18.1.1.2"
OID_ALERT_CODE = "1.3.6.1.2.1.43.18.1.1.7"
OID_ALERT_DESC = "1.3.6.1.2.1.43.18.1.1.8"
OID_PRINTER_MIB = "1.3.6.1.2.1.43"
OID_STATUS_WALK_TABLES = (
    OID_SERIAL_TABLE,
    OID_SUPPLY_DESC,
    OID_SUPPLY_UNIT,
    OID_SUPPLY_MAX,
    OID_SUPPLY_LEVEL,
    OID_INPUT_NAME,
    OID_INPUT_DESC,
    OID_INPUT_LEVEL,
    OID_INPUT_MAX,
    OID_INPUT_STATUS,
    OID_ALERT_SEVERITY,
    OID_ALERT_CODE,
    OID_ALERT_DESC,
)
DISCOVERY_SERVICE_TYPES = (
    "_printer._tcp",
    "_ipp._tcp",
    "_ipps._tcp",
    "_pdl-datastream._tcp",
    "_canon-bjnp1._tcp",
    "_canon-bjnp2._tcp",
    "_canon-bjnp3._tcp",
    "_canon-bjnp4._tcp",
)
DISCOVERY_PORTS = (9100, 631, 8611, 8612, 8613, 8614)


class PrinterServiceError(Exception):
    status_code = 502

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class PrinterMissingHostError(PrinterServiceError):
    status_code = 400


class PrinterTimeoutError(PrinterServiceError):
    status_code = 504


class PrinterSnmpUnavailableError(PrinterServiceError):
    status_code = 503


class PrinterUnsupportedError(PrinterServiceError):
    status_code = 422


@dataclass(frozen=True)
class SnmpRow:
    oid: str
    kind: str
    value: str


@dataclass(frozen=True)
class ProbeDevice:
    id: int
    name: str
    brand: str
    model: str | None
    host: str
    device_key: str | None
    device_uuid: str | None
    device_type: str | None
    channel: int
    is_enabled: bool
    last_state: str | None
    created_at: str
    updated_at: str


def _config(device: Device) -> dict[str, Any]:
    config = {
        "community": DEFAULT_COMMUNITY,
        "timeout": DEFAULT_TIMEOUT_SECONDS,
        "retries": DEFAULT_RETRIES,
    }
    if not device.device_key:
        return config
    value = device.device_key.strip()
    if not value:
        return config
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PrinterUnsupportedError("Printer SNMP settings JSON is invalid.") from exc
        config["community"] = str(parsed.get("community") or parsed.get("snmp_community") or config["community"])
        config["timeout"] = float(parsed.get("timeout") or parsed.get("timeout_seconds") or config["timeout"])
        config["retries"] = int(parsed.get("retries") if parsed.get("retries") is not None else config["retries"])
        if parsed.get("version") or parsed.get("snmp_version"):
            config["version"] = str(parsed.get("version") or parsed.get("snmp_version"))
        return config
    config["community"] = value
    return config


def _device_key_json(device: Device) -> dict[str, Any]:
    if not device.device_key:
        return {}
    value = device.device_key.strip()
    if not value.startswith("{"):
        return {"community": value}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _host(device: Device) -> str:
    host = (device.host or "").strip()
    if not host:
        raise PrinterMissingHostError("Printer host is missing.")
    return re.sub(r"^https?://", "", host).split("/", 1)[0]


def _snmp_command(device: Device, oid: str, tool: str = "snmpwalk", version: str | None = None) -> list[str]:
    config = _config(device)
    snmp_version = version or str(config.get("version") or "2c")
    return [
        tool,
        "-v" + snmp_version,
        "-c",
        str(config["community"]),
        "-t",
        str(config["timeout"]),
        "-r",
        str(config["retries"]),
        "-On",
        _host(device),
        oid,
    ]


def _run_snmp_sync(device: Device, oid: str, tool: str = "snmpwalk") -> str:
    config = _config(device)
    configured_version = config.get("version")
    versions = [str(configured_version)] if configured_version else ["2c", "1"]
    last_timeout = False
    for version in versions:
        try:
            completed = subprocess.run(
                _snmp_command(device, oid, tool, version),
                capture_output=True,
                text=True,
                timeout=float(config["timeout"]) + 2,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PrinterSnmpUnavailableError("SNMP tools are not installed on this Sentinel machine.") from exc
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if parse_snmp_output(stdout):
                return stdout
            last_timeout = True
            continue
        except OSError as exc:
            raise PrinterServiceError(f"Could not run SNMP status check: {exc}") from exc

        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        if completed.returncode == 0:
            return completed.stdout
        if parse_snmp_output(completed.stdout):
            return completed.stdout
        lowered = output.lower()
        if "timeout" in lowered or "no response" in lowered:
            last_timeout = True
            continue
        raise PrinterServiceError(output or "Printer SNMP status check failed.")
    if last_timeout:
        raise PrinterTimeoutError("Printer did not respond to SNMP.")
    raise PrinterServiceError("Printer SNMP status check failed.")


async def _snmp_walk(device: Device, oid: str) -> dict[str, SnmpRow]:
    return parse_snmp_output(await asyncio.to_thread(_run_snmp_sync, device, oid, "snmpwalk"))


async def _snmp_get(device: Device, oid: str) -> dict[str, SnmpRow]:
    return parse_snmp_output(await asyncio.to_thread(_run_snmp_sync, device, oid, "snmpget"))


def parse_snmp_output(output: str) -> dict[str, SnmpRow]:
    rows: dict[str, SnmpRow] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or " = " not in line:
            continue
        oid_part, value_part = line.split(" = ", 1)
        oid = oid_part.strip().lstrip(".")
        if ": " in value_part:
            kind, value = value_part.split(": ", 1)
        else:
            kind, value = "VALUE", value_part
        rows[oid] = SnmpRow(oid=oid, kind=kind.strip(), value=_clean_snmp_value(value))
    return rows


def _clean_snmp_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.replace('\\"', '"')


def _table_rows(rows: dict[str, SnmpRow], base_oid: str) -> dict[str, SnmpRow]:
    prefix = base_oid + "."
    return {oid[len(prefix):]: row for oid, row in rows.items() if oid.startswith(prefix)}


def _row_value(rows: dict[str, SnmpRow], base_oid: str) -> str | None:
    table = _table_rows(rows, base_oid)
    if not table:
        return None
    return next(iter(table.values())).value


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


def _supply_status(level: int | None, max_capacity: int | None, percent: int | None) -> str:
    if level is None:
        return "unknown"
    if level < 0:
        return "unknown"
    if level == 0:
        return "empty"
    if percent is not None and percent <= 10:
        return "low"
    if percent is not None and percent <= 25:
        return "watch"
    if max_capacity and level <= 1:
        return "low"
    return "ok"


def _guess_color(description: str) -> str | None:
    text = description.lower()
    color_map = [
        ("photo black", "Photo Black"),
        ("matte black", "Matte Black"),
        ("black", "Black"),
        ("cyan", "Cyan"),
        ("magenta", "Magenta"),
        ("yellow", "Yellow"),
        ("orange", "Orange"),
        ("red", "Red"),
        ("blue", "Blue"),
        ("gray", "Gray"),
        ("grey", "Gray"),
        ("waste", "Waste"),
        ("maintenance", "Maintenance"),
    ]
    for needle, color in color_map:
        if needle in text:
            return color
    # Canon imagePROGRAF devices commonly expose compact tank labels through
    # Printer-MIB (for example "Ink Tank MBK" and "Ink Tank GY") instead of
    # spelling out the color. Match whole tokens so model names or ordinary
    # words cannot be mistaken for a supply color.
    compact_color_map = {
        "mbk": "Matte Black",
        "pbk": "Photo Black",
        "bk": "Black",
        "k": "Black",
        "c": "Cyan",
        "m": "Magenta",
        "y": "Yellow",
        "o": "Orange",
        "gy": "Gray",
        "g": "Gray",
    }
    tokens = re.findall(r"[a-z]+", text)
    for token in tokens:
        if token in compact_color_map:
            return compact_color_map[token]
    return None


def _is_waste_supply(description: str) -> bool:
    text = description.lower()
    return "waste" in text or "wasted ink" in text


def _is_measured_ink_supply(supply: dict[str, Any]) -> bool:
    text = " ".join(str(supply.get(field) or "") for field in ("color", "name", "reportedName"))
    supply_type = supply.get("supplyType")
    return supply_type in (None, "ink") and not _is_waste_supply(text) and "maintenance" not in text.lower()


def _display_supply_name(description: str) -> str:
    if _is_waste_supply(description):
        return "Waste Collection Unit"
    return description


def _supply_type(description: str) -> str:
    text = description.lower()
    if "ribbon" in text or "film" in text:
        return "ribbon"
    if "ink" in text:
        return "ink"
    if "waste" in text or "maintenance" in text:
        return "maintenance"
    return "supply"


def _is_percentage_supply(description: str) -> bool:
    text = description.lower()
    return any(needle in text for needle in (" ink", "ink ", "ribbon", "film", "waste", "maintenance"))


def _normalized_max_capacity(description: str, raw_level: int | None, max_capacity: int | None) -> int | None:
    if max_capacity is not None:
        return max_capacity
    if raw_level is None or raw_level < 0 or raw_level > 100:
        return None
    if not _is_percentage_supply(description):
        return None
    return 100


def _supply_sort_key(supply: dict[str, Any]) -> tuple[int, str]:
    text = " ".join(str(supply.get(field) or "").lower() for field in ("color", "name", "reportedName"))
    order = [
        ("cyan", 0),
        ("magenta", 1),
        ("yellow", 2),
        ("photo black", 3),
        ("matte black", 4),
        ("black", 5),
        ("gray", 6),
        ("grey", 6),
        ("orange", 7),
        ("waste", 8),
        ("maintenance", 8),
    ]
    for needle, position in order:
        if needle in text:
            return (position, str(supply.get("id") or ""))
    return (50, str(supply.get("id") or ""))


def _unit_label(unit_code: int | None) -> str:
    return {
        3: "sheets",
        7: "impressions",
        8: "sheets",
        11: "hours",
        12: "thousandths of ounces",
        13: "tenths of grams",
        14: "hundreths of fluid ounces",
        15: "tenths of milliliters",
        16: "feet",
        17: "meters",
    }.get(unit_code or 0, "units")


def _media_level_label(level: int | None) -> str | None:
    return {
        -1: "Other",
        -2: "Level unknown",
        -3: "Loaded",
    }.get(level)


def _media_status_label(status: int | None) -> str | None:
    if status in (None, 0):
        return None
    return {
        1: "Other",
        2: "Unknown",
        3: "Available",
        4: "Non-critical",
        5: "Critical",
        6: "Unavailable",
    }.get(status, f"Status {status}")


def _alert_severity_label(severity: int | None) -> str | None:
    if severity is None:
        return None
    return {
        1: "Other",
        2: "Unknown",
        3: "Critical",
        4: "Warning",
        5: "Warning",
    }.get(severity, f"Severity {severity}")


def supplies_from_snmp_rows(rows: dict[str, SnmpRow]) -> list[dict[str, Any]]:
    descriptions = _table_rows(rows, OID_SUPPLY_DESC)
    units = _table_rows(rows, OID_SUPPLY_UNIT)
    max_values = _table_rows(rows, OID_SUPPLY_MAX)
    levels = _table_rows(rows, OID_SUPPLY_LEVEL)
    keys = sorted(set(descriptions) | set(units) | set(max_values) | set(levels), key=_natural_key)
    supplies: list[dict[str, Any]] = []
    for key in keys:
        description = descriptions.get(key).value if key in descriptions else f"Supply {key}"
        raw_level = _as_int(levels.get(key).value if key in levels else None)
        max_capacity = _as_int(max_values.get(key).value if key in max_values else None)
        max_capacity = _normalized_max_capacity(description, raw_level, max_capacity)
        unit_code = _as_int(units.get(key).value if key in units else None)
        level = raw_level
        raw_percent = None
        if raw_level is not None and max_capacity is not None and raw_level >= 0 and max_capacity > 0:
            raw_percent = max(0, min(100, round((raw_level / max_capacity) * 100)))
        if _is_waste_supply(description) and raw_level is not None and max_capacity is not None and raw_level >= 0 and max_capacity > 0:
            level = max(0, min(max_capacity, max_capacity - raw_level))
        percent = None
        if level is not None and max_capacity is not None and level >= 0 and max_capacity > 0:
            percent = max(0, min(100, round((level / max_capacity) * 100)))
        supplies.append({
            "id": key,
            "name": _display_supply_name(description),
            "reportedName": description,
            "color": _guess_color(description),
            "level": level,
            "rawLevel": raw_level,
            "max": max_capacity,
            "percent": percent,
            "rawPercent": raw_percent,
            "unit": _unit_label(unit_code),
            "status": _supply_status(level, max_capacity, percent),
            "measurement": "remaining" if _is_waste_supply(description) else "level",
            "supplyType": _supply_type(description),
        })
    return sorted(supplies, key=_supply_sort_key)


def media_from_snmp_rows(rows: dict[str, SnmpRow]) -> list[dict[str, Any]]:
    names = _table_rows(rows, OID_INPUT_NAME)
    descriptions = _table_rows(rows, OID_INPUT_DESC)
    levels = _table_rows(rows, OID_INPUT_LEVEL)
    max_values = _table_rows(rows, OID_INPUT_MAX)
    statuses = _table_rows(rows, OID_INPUT_STATUS)
    keys = sorted(set(names) | set(descriptions) | set(levels) | set(max_values) | set(statuses), key=_natural_key)
    media: list[dict[str, Any]] = []
    for key in keys:
        name = names.get(key).value if key in names else descriptions.get(key).value if key in descriptions else f"Input {key}"
        raw_level = _as_int(levels.get(key).value if key in levels else None)
        level = raw_level if raw_level is not None and raw_level >= 0 else None
        max_capacity = _as_int(max_values.get(key).value if key in max_values else None)
        status_code = _as_int(statuses.get(key).value if key in statuses else None)
        percent = None
        if level is not None and max_capacity is not None and level >= 0 and max_capacity > 0:
            percent = max(0, min(100, round((level / max_capacity) * 100)))
        media.append({
            "id": key,
            "name": name,
            "description": descriptions.get(key).value if key in descriptions else None,
            "level": level,
            "rawLevel": raw_level,
            "levelLabel": _media_level_label(raw_level),
            "max": max_capacity,
            "unit": "sheets",
            "percent": percent,
            "status": _media_status_label(status_code),
            "rawStatus": status_code,
        })
    return media


def alerts_from_snmp_rows(rows: dict[str, SnmpRow]) -> list[dict[str, Any]]:
    severities = _table_rows(rows, OID_ALERT_SEVERITY)
    codes = _table_rows(rows, OID_ALERT_CODE)
    descriptions = _table_rows(rows, OID_ALERT_DESC)
    keys = sorted(set(severities) | set(codes) | set(descriptions), key=_natural_key)
    alerts: list[dict[str, Any]] = []
    for key in keys:
        description = _clean_alert_description(descriptions.get(key).value if key in descriptions else "")
        severity = _as_int(severities.get(key).value if key in severities else None)
        code = _as_int(codes.get(key).value if key in codes else None)
        if not description and not severity and not code:
            continue
        alerts.append({
            "id": key,
            "severity": severity,
            "severityLabel": _alert_severity_label(severity),
            "code": code,
            "description": description or f"Printer alert {code or key}",
        })
    return alerts


def _clean_alert_description(description: str) -> str:
    return re.sub(r"\{\d+\}$", "", description or "").strip()


def _apply_canon_gp_low_supply_alerts(
    device: Device,
    sys_descr: str | None,
    supplies: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
) -> None:
    """Treat Canon GP zero readings accompanied by a low alert as threshold-only.

    GP-series printers can return zero from prtMarkerSuppliesLevel once a tank is
    below the reporting threshold while still reporting the tank as low through
    prtAlertTable. A zero in that combination is not proof that the tank is
    empty, so avoid presenting a fabricated 0% measurement.
    """
    identity = " ".join(str(value or "") for value in (device.model, sys_descr)).lower()
    if "canon" not in identity or not re.search(r"\bgp[- ]?\d", identity):
        return

    low_alert_text = " ".join(
        str(alert.get("description") or "").lower()
        for alert in alerts
        if "supply low" in str(alert.get("description") or "").lower()
    )
    if not low_alert_text:
        return

    for supply in supplies:
        if supply.get("rawLevel") != 0 or supply.get("supplyType") != "ink":
            continue
        color = str(supply.get("color") or "").lower()
        alert_matches = color and color in low_alert_text
        if color == "photo black":
            alert_matches = "black" in low_alert_text
        if not alert_matches:
            continue
        supply.update({
            "level": None,
            "percent": None,
            "status": "low",
            "levelLabel": "Low",
            "measurement": "threshold-only",
        })


def build_status(device: Device, rows: dict[str, SnmpRow], checked_at: str | None = None) -> dict[str, Any]:
    supplies = supplies_from_snmp_rows(rows)
    media = media_from_snmp_rows(rows)
    alerts = alerts_from_snmp_rows(rows)
    serial = _row_value(rows, OID_SERIAL_TABLE)
    sys_descr = rows.get(OID_SYS_DESCR).value if OID_SYS_DESCR in rows else None
    sys_name = rows.get(OID_SYS_NAME).value if OID_SYS_NAME in rows else None
    _apply_canon_gp_low_supply_alerts(device, sys_descr, supplies, alerts)
    levels_with_percent = [
        item["percent"]
        for item in supplies
        if _is_measured_ink_supply(item) and item.get("percent") is not None
    ]
    lowest_percent = min(levels_with_percent) if levels_with_percent else None
    needs_attention = bool(alerts) or any(item.get("status") in {"empty", "low"} for item in supplies)
    identity = " ".join(str(value or "") for value in (device.model, sys_descr, sys_name)).lower()
    is_card_printer = "magicard" in identity
    supply_label = "Ribbon and supplies" if is_card_printer else "Ink and supplies"

    appliance = {
        "type": "printer",
        "title": "Printer status",
        "status": "Needs attention" if needs_attention else "Ready",
        "message": alerts[0]["description"] if alerts else "",
        "model": device.model or _model_from_sys_descr(sys_descr),
        "serial": serial,
        "firmware": sys_descr,
        "systemName": sys_name,
        "inkLevels": supplies,
        "supplyLabel": supply_label,
        "supplyMetricLabel": "Lowest supply" if is_card_printer else "Lowest ink",
        "emptySupplyMessage": "Ribbon data unavailable" if is_card_printer else "Ink data unavailable",
        "media": media,
        "alerts": alerts,
        "lowestInkPercent": lowest_percent,
        "checkedAt": checked_at,
    }
    return {
        "is_on": True,
        "appliance": appliance,
        "raw": {
            "source": "snmp",
            "host": device.host,
            "sysDescr": sys_descr,
            "sysName": sys_name,
            "serial": serial,
            "rowCount": len(rows),
        },
    }


def offline_status(device: Device, cached_state: dict[str, Any] | None, message: str, checked_at: str | None = None) -> dict[str, Any]:
    cached_appliance = dict((cached_state or {}).get("appliance") or {})
    cached_appliance.update({
        "type": "printer",
        "title": cached_appliance.get("title") or "Printer status",
        "status": "Offline",
        "message": message,
        "stale": True,
        "lastOnlineAt": cached_appliance.get("checkedAt") or (cached_state or {}).get("checked_at"),
        "checkedAt": checked_at,
    })
    if not cached_appliance.get("model"):
        cached_appliance["model"] = device.model
    return {
        "is_on": False,
        "appliance": cached_appliance,
        "raw": {
            "source": "snmp",
            "host": device.host,
            "error": message,
            "stale": True,
        },
    }


async def get_status(device: Device, checked_at: str | None = None) -> dict[str, Any]:
    rows: dict[str, SnmpRow] = {}
    try:
        rows.update(await _snmp_get(device, OID_SYS_DESCR))
    except PrinterServiceError:
        remote_status = await asyncio.to_thread(_canon_remote_ui_status, device, checked_at)
        if remote_status:
            _apply_manual_ink_refills(device, remote_status)
            return remote_status
        if _is_magicard(device) and await _tcp_port_open(_host(device), 9100, 2):
            return magicard_network_status(device, checked_at)
        raise
    optional_reads = [
        _snmp_get(device, OID_SYS_NAME),
        *( _snmp_walk(device, oid) for oid in OID_STATUS_WALK_TABLES ),
    ]
    for result in await asyncio.gather(*optional_reads, return_exceptions=True):
        if isinstance(result, Exception):
            continue
        rows.update(result)
    if not rows:
        raise PrinterUnsupportedError("Printer did not return SNMP status data.")
    status = build_status(device, rows, checked_at)
    await asyncio.to_thread(_apply_canon_remote_ui_ink, device, status)
    _apply_manual_ink_refills(device, status)
    return status


def _is_magicard(device: Device) -> bool:
    return "magicard" in " ".join(str(value or "") for value in (device.name, device.model)).lower()


def magicard_network_status(device: Device, checked_at: str | None = None) -> dict[str, Any]:
    """Return useful reachability state when a Magicard exposes raw printing but no SNMP."""
    config = _device_key_json(device)
    return {
        "is_on": True,
        "appliance": {
            "type": "printer",
            "title": "Badge printer status",
            "status": "Online",
            "message": "Connected for printing. Detailed ribbon and card status is unavailable from this printer interface.",
            "model": device.model or "Magicard 300",
            "serial": config.get("serial"),
            "printheadSerial": config.get("printhead_serial"),
            "firmware": config.get("firmware"),
            "dyeFilmType": config.get("dye_film_type"),
            "handFeed": config.get("hand_feed"),
            "systemName": None,
            "inkLevels": [],
            "supplyLabel": "Ribbon and supplies",
            "supplyMetricLabel": "Lowest supply",
            "emptySupplyMessage": "Ribbon level unavailable",
            "media": [],
            "alerts": [],
            "lowestInkPercent": None,
            "checkedAt": checked_at,
        },
        "raw": {
            "source": "tcp",
            "host": device.host,
            "port": 9100,
            "snmpSupported": False,
            "statusDetail": "Raw printing is reachable; SNMP status is unavailable.",
        },
    }


def _apply_canon_remote_ui_ink(device: Device, status: dict[str, Any]) -> None:
    appliance = status.get("appliance") or {}
    identity = " ".join(str(value or "") for value in (
        device.model,
        appliance.get("model"),
        appliance.get("firmware"),
        appliance.get("systemName"),
    )).lower()
    if "canon" not in identity:
        return
    remote_levels = _canon_remote_ui_ink_levels(_host(device))
    if not remote_levels:
        return
    by_color = {
        str(item.get("color") or "").lower(): item
        for item in appliance.get("inkLevels") or []
        if item.get("color")
    }
    for remote in remote_levels:
        supply = by_color.get(str(remote.get("color") or "").lower())
        if not supply:
            continue
        percent = remote.get("percent")
        supply["level"] = percent
        supply["percent"] = percent
        supply["remoteUiLevelIndex"] = remote.get("levelIndex")
        supply["remoteUiMarker"] = remote.get("marker")
        supply["status"] = remote.get("status") or _supply_status(percent, 100, percent)
        supply["levelLabel"] = "Low" if remote.get("status") == "low" and percent is None else None
        supply["measurement"] = "threshold-only" if percent is None else "remote-ui-estimate"
    levels_with_percent = [
        item["percent"] for item in appliance.get("inkLevels") or []
        if _is_measured_ink_supply(item) and item.get("percent") is not None
    ]
    appliance["lowestInkPercent"] = min(levels_with_percent) if levels_with_percent else None
    has_attention = bool(appliance.get("alerts")) or any(item.get("status") in {"empty", "low"} for item in appliance.get("inkLevels") or [])
    appliance["status"] = "Needs attention" if has_attention else "Ready"
    if not has_attention:
        appliance["message"] = ""
    status.setdefault("raw", {})["remoteUiInk"] = True


def _apply_manual_ink_refills(device: Device, status: dict[str, Any]) -> None:
    config = _device_key_json(device)
    refills = config.get("ink_refills") if isinstance(config, dict) else None
    if not isinstance(refills, dict):
        return
    appliance = status.get("appliance") or {}
    changed = False
    for supply in appliance.get("inkLevels") or []:
        color = str(supply.get("color") or "").lower()
        if not color or color not in refills:
            continue
        refill = refills.get(color)
        if not isinstance(refill, dict):
            continue
        supply["level"] = 100
        supply["percent"] = 100
        supply["status"] = "ok"
        supply["measurement"] = "manual-refill"
        supply["manualRefillAt"] = refill.get("refilled_at")
        changed = True
    if not changed:
        return
    levels_with_percent = [
        item["percent"] for item in appliance.get("inkLevels") or []
        if _is_measured_ink_supply(item) and item.get("percent") is not None
    ]
    appliance["lowestInkPercent"] = min(levels_with_percent) if levels_with_percent else None
    has_attention = bool(appliance.get("alerts")) or any(item.get("status") in {"empty", "low"} for item in appliance.get("inkLevels") or [])
    appliance["status"] = "Needs attention" if has_attention else "Ready"
    if not has_attention:
        appliance["message"] = ""
    status.setdefault("raw", {})["manualInkRefill"] = True


def _canon_remote_ui_ink_levels(host: str) -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://{host}/JS_MDL/model.js", timeout=2) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError):
        return []
    return _parse_canon_remote_ui_ink_levels(text)


def _canon_remote_ui_status(device: Device, checked_at: str | None = None) -> dict[str, Any] | None:
    identity = " ".join(str(value or "") for value in (device.name, device.model)).lower()
    if "canon" not in identity:
        return None
    levels = _canon_remote_ui_ink_levels(_host(device))
    if not levels:
        return None
    supplies = []
    for index, remote in enumerate(levels):
        percent = remote.get("percent")
        threshold_only = percent is None
        supplies.append({
            "id": f"remote.{index + 1}",
            "name": remote.get("name") or f"{remote.get('color') or 'Canon'} Ink Tank",
            "reportedName": remote.get("name"),
            "color": remote.get("color"),
            "level": percent,
            "rawLevel": remote.get("levelIndex"),
            "max": 100,
            "percent": percent,
            "rawPercent": percent,
            "unit": "estimated level",
            "status": remote.get("status") or _supply_status(percent, 100, percent),
            "levelLabel": "Low" if threshold_only else None,
            "measurement": "threshold-only" if threshold_only else "remote-ui-estimate",
            "remoteUiLevelIndex": remote.get("levelIndex"),
            "remoteUiMarker": remote.get("marker"),
            "supplyType": "ink",
        })
    known = [item["percent"] for item in supplies if item.get("percent") is not None]
    needs_attention = any(item.get("status") in {"empty", "low"} for item in supplies)
    return {
        "is_on": True,
        "appliance": {
            "type": "printer",
            "title": "Printer status",
            "status": "Needs attention" if needs_attention else "Ready",
            "message": "One or more ink tanks are low." if needs_attention else "",
            "model": device.model,
            "serial": None,
            "firmware": None,
            "systemName": None,
            "inkLevels": supplies,
            "supplyLabel": "Ink and supplies",
            "supplyMetricLabel": "Lowest ink",
            "emptySupplyMessage": "Ink data unavailable",
            "media": [],
            "alerts": [],
            "lowestInkPercent": min(known) if known else None,
            "checkedAt": checked_at,
        },
        "raw": {
            "source": "canon-remote-ui",
            "host": device.host,
            "remoteUiInk": True,
            "snmpSupported": False,
        },
    }


def _parse_canon_remote_ui_ink_levels(text: str) -> list[dict[str, Any]]:
    fallback_color_names = {
        0: "Black",
        1: "Cyan",
        2: "Magenta",
        3: "Yellow",
    }
    css_color_names = {
        "InkGry": "Gray",
        "InkPbk": "Photo Black",
        "InkOra": "Orange",
        "InkMbk": "Matte Black",
        "InkYel": "Yellow",
        "InkMaz": "Magenta",
        "InkCia": "Cyan",
        "InkBlk": "Black",
        "InkRed": "Red",
        "InkBlu": "Blue",
        "InkBlue": "Blue",
        "InkGre": "Green",
    }
    color_names = dict(fallback_color_names)
    color_array = re.search(r"var\s+inkCOL\s*=\s*\[([^\]]+)\]", text)
    if color_array:
        entries = re.findall(r"['\"]([^'\"]+)['\"]", color_array.group(1))
        color_names = {index: css_color_names.get(value) for index, value in enumerate(entries)}
    level_percent = {
        0: 100,
        1: 90,
        2: 80,
        3: 70,
        4: 60,
        5: 50,
        6: 40,
        7: 30,
        8: 20,
        9: 10,
        10: 0,
    }
    levels = []
    pattern = r"inktank\[\d+\]\s*=\s*\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*['\"]([^'\"]*)['\"])?\s*\]"
    for match in re.finditer(pattern, text):
        color_index = int(match.group(1))
        level_index = int(match.group(2))
        marker = int(match.group(3))
        color = color_names.get(color_index)
        if color is None or level_index not in level_percent:
            continue
        percent = level_percent[level_index]
        status = _supply_status(percent, 100, percent)
        if marker == 1 and level_index == 10:
            percent = None
            status = "low"
        elif marker == 2:
            percent = 0
            status = "empty"
        levels.append({
            "color": color,
            "name": match.group(4),
            "percent": percent,
            "levelIndex": level_index,
            "marker": marker,
            "status": status,
        })
    cartridge = re.search(r"g_cartridge_rest\s*=\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*\]", text)
    if cartridge:
        level_index = int(cartridge.group(1))
        marker = int(cartridge.group(2))
        if level_index >= 0 and marker >= 0:
            percent = max(0, min(100, level_index * 10))
            status = "empty" if marker == 2 else "low" if marker == 1 else _supply_status(percent, 100, percent)
            levels.append({
                "color": "Waste",
                "name": "Maintenance Cartridge",
                "percent": percent,
                "levelIndex": level_index,
                "marker": marker,
                "status": status,
            })
    return levels


async def discover_printers(
    timeout_seconds: float = 3.0,
    subnets: list[str] | None = None,
    scan_routed_subnets: bool = True,
    community: str = DEFAULT_COMMUNITY,
    model_hint: str | None = None,
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}

    for candidate in await asyncio.to_thread(_cups_candidates):
        _merge_candidate(candidates, candidate)

    for candidate in _requested_host_candidates(subnets or [], model_hint):
        _merge_candidate(candidates, candidate)

    browse_tasks = [_bonjour_candidates(service_type, timeout_seconds) for service_type in DISCOVERY_SERVICE_TYPES]
    for result in await asyncio.gather(*browse_tasks, return_exceptions=True):
        if isinstance(result, Exception):
            continue
        for candidate in result:
            _merge_candidate(candidates, candidate)

    targets = _discovery_subnets(subnets or [], scan_routed_subnets)
    scanned_subnets: list[str] = []
    for subnet in targets:
        scanned_subnets.append(subnet)
        for candidate in await _scan_printer_ports(subnet, max(0.2, timeout_seconds / 8)):
            _merge_candidate(candidates, candidate)

    probe_tasks = [_enrich_discovery_candidate(candidate, community) for candidate in candidates.values()]
    probed = await asyncio.gather(*probe_tasks, return_exceptions=True)
    printers: list[dict[str, Any]] = []
    for result in probed:
        if isinstance(result, Exception):
            continue
        printers.append(result)

    printers.sort(key=lambda item: (not item.get("snmp_supported"), item.get("name") or item.get("host") or ""))
    return {"printers": printers, "scanned_subnets": scanned_subnets}


def _merge_candidate(candidates: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> None:
    host = (candidate.get("host") or "").strip()
    name = (candidate.get("name") or "").strip()
    key = host.lower() if host else f"name:{name.lower()}:{candidate.get('service_type') or ''}"
    if not key or key == "name::":
        return
    existing = candidates.get(key)
    if not existing:
        candidates[key] = candidate
        return
    existing_sources = set(existing.get("sources") or [existing.get("source")])
    existing_sources.add(candidate.get("source"))
    existing["sources"] = sorted(source for source in existing_sources if source)
    for field in ("host", "name", "model", "service_type", "port", "uuid"):
        if not existing.get(field) and candidate.get(field):
            existing[field] = candidate[field]


def _command_output(args: list[str], timeout_seconds: float) -> str:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        return "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return "\n".join(part for part in (stdout, stderr) if part)
    except (FileNotFoundError, OSError):
        return ""


def _cups_candidates() -> list[dict[str, Any]]:
    output = _command_output(["lpstat", "-v"], 2)
    candidates = []
    for line in output.splitlines():
        match = re.match(r"device for (?P<name>[^:]+):\s+(?P<uri>\S+)", line.strip())
        if not match:
            continue
        uri = match.group("uri")
        candidate = _candidate_from_printer_uri(uri)
        candidate["name"] = _clean_name(match.group("name"))
        candidate["source"] = "cups"
        candidate["sources"] = ["cups"]
        candidates.append(candidate)
    return candidates


def _candidate_from_printer_uri(uri: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(uri)
    candidate: dict[str, Any] = {"uri": uri, "host": "", "model": None}
    if parsed.scheme in {"socket", "ipp", "ipps", "lpd", "http", "https"}:
        candidate["host"] = parsed.hostname or ""
        candidate["port"] = parsed.port
    elif parsed.scheme == "dnssd":
        value = urllib.parse.unquote(parsed.netloc + parsed.path).strip("/")
        match = re.match(r"(?P<name>.+)\.(?P<type>_[^.]+\._tcp)\.local\.?", value)
        if match:
            resolved = _resolve_bonjour(match.group("name"), match.group("type"), "local.", 2)
            candidate.update(resolved)
            candidate["service_type"] = match.group("type")
    return candidate


async def _bonjour_candidates(service_type: str, timeout_seconds: float) -> list[dict[str, Any]]:
    output = await asyncio.to_thread(_command_output, ["dns-sd", "-B", service_type, "local."], timeout_seconds)
    candidates = []
    for line in output.splitlines():
        match = re.search(r"\sAdd\s+\d+\s+\d+\s+(?P<domain>\S+)\s+(?P<type>_\S+)\s+(?P<name>.+)$", line)
        if not match:
            continue
        service_name = match.group("name").strip()
        service_domain = match.group("domain").strip()
        service = match.group("type").strip().rstrip(".")
        resolved = await asyncio.to_thread(_resolve_bonjour, service_name, service, service_domain, timeout_seconds)
        candidate = {
            "name": _clean_name(service_name),
            "source": "bonjour",
            "sources": ["bonjour"],
            "service_type": service,
            **resolved,
        }
        candidates.append(candidate)
    return candidates


def _resolve_bonjour(name: str, service_type: str, domain: str, timeout_seconds: float) -> dict[str, Any]:
    output = _command_output(["dns-sd", "-L", name, service_type, domain], timeout_seconds)
    result: dict[str, Any] = {"host": "", "port": None, "model": _guess_model(name)}
    endpoint = re.search(r"can be reached at (?P<host>[^:]+):(?P<port>\d+)", output)
    if endpoint:
        result["host"] = endpoint.group("host").rstrip(".")
        result["port"] = int(endpoint.group("port"))
    txt_model = _txt_record_value(output, "ty")
    if txt_model:
        result["model"] = _guess_model(txt_model) or txt_model.strip().replace("\\ ", " ")
    uuid_match = re.search(r"UUID=([A-Za-z0-9_-]+)", output, re.IGNORECASE)
    if uuid_match:
        result["uuid"] = uuid_match.group(1)
    return result


def _txt_record_value(output: str, key: str) -> str | None:
    prefix = key + "="
    for chunk in re.findall(r'"([^"]+)"', output):
        if chunk.startswith(prefix):
            return chunk[len(prefix):]
    match = re.search(r"(?:^|\s)" + re.escape(prefix) + r"([^\n]+)", output)
    if not match:
        return None
    value = match.group(1).strip()
    for marker in (" usb_", " product=", " pdl=", " rp=", " qtotal=", " Color=", " Duplex=", " Scan=", " Fax=", " kind=", " PaperMax=", " URF=", " UUID=", " TLS="):
        if marker in value:
            value = value.split(marker, 1)[0]
    return value.strip() or None


def _discovery_subnets(requested: list[str], scan_routed_subnets: bool) -> list[str]:
    values = list(requested)
    if not values:
        values.append(discovery.default_subnet())
    if scan_routed_subnets:
        values.extend(camera_service.routed_private_subnets())
    normalized = []
    seen = set()
    for value in values:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            continue
        if not isinstance(network, ipaddress.IPv4Network) or not network.is_private or network.num_addresses > 1024:
            continue
        text = str(network)
        if text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


async def _scan_printer_ports(subnet: str, timeout_seconds: float) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    hosts = _network_hosts(subnet)
    for port in DISCOVERY_PORTS:
        results = await asyncio.gather(*[
            _tcp_port_open(host, port, timeout_seconds) for host in hosts
        ])
        for host in [item for item in results if item]:
            found.setdefault(host, {
                "host": host,
                "name": f"Printer {host}",
                "model": None,
                "source": "network_scan",
                "sources": ["network_scan"],
                "ports": [],
            })
            found[host]["ports"].append(port)
    return list(found.values())


def _requested_host_candidates(values: list[str], model_hint: str | None = None) -> list[dict[str, Any]]:
    candidates = []
    model = model_hint.strip() if model_hint else None
    for value in values:
        text = value.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            host = re.sub(r"^https?://", "", text).split("/", 1)[0].strip()
            if host:
                candidates.append({
                    "host": host,
                    "name": model or f"Printer {host}",
                    "model": model,
                    "source": "direct",
                    "sources": ["direct"],
                })
            continue
        if isinstance(network, ipaddress.IPv4Network) and network.num_addresses == 1:
            host = str(network.network_address)
            candidates.append({
                "host": host,
                "name": model or f"Printer {host}",
                "model": model,
                "source": "direct",
                "sources": ["direct"],
            })
    return candidates


def _network_hosts(subnet: str) -> list[str]:
    network = ipaddress.ip_network(subnet, strict=False)
    if isinstance(network, ipaddress.IPv4Network) and network.num_addresses == 1:
        return [str(network.network_address)]
    return [str(host) for host in network.hosts()]


async def _tcp_port_open(host: str, port: int, timeout_seconds: float) -> str | None:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
        writer.close()
        await writer.wait_closed()
        return host
    except (asyncio.TimeoutError, OSError):
        return None


async def _enrich_discovery_candidate(candidate: dict[str, Any], community: str) -> dict[str, Any]:
    host = candidate.get("host") or ""
    if host:
        host = await asyncio.to_thread(_resolve_host_address, host)
        candidate["host"] = host or candidate.get("host") or ""
    if not candidate.get("model"):
        candidate["model"] = _guess_model(candidate.get("name") or "")
    if host and (not candidate.get("model") or _is_generic_printer_name(candidate.get("name"))):
        ipp_candidate = await asyncio.to_thread(_ipp_attribute_candidate, host)
        if ipp_candidate:
            for field in ("name", "model", "uri"):
                if ipp_candidate.get(field) and (field != "name" or _is_generic_printer_name(candidate.get("name"))):
                    candidate[field] = ipp_candidate[field]
            candidate["sources"] = sorted(set(candidate.get("sources") or [candidate.get("source")]) | {"ipp"})
    if not host:
        candidate["snmp_supported"] = False
        return candidate
    probe = ProbeDevice(
        id=0,
        name=candidate.get("name") or host,
        brand="printer",
        model=candidate.get("model"),
        host=host,
        device_key=json.dumps({"community": community, "timeout": 1, "retries": 0}),
        device_uuid=None,
        device_type="printer",
        channel=0,
        is_enabled=True,
        last_state=None,
        created_at="",
        updated_at="",
    )
    try:
        status = await get_status(probe)
    except PrinterServiceError as exc:
        candidate["snmp_supported"] = False
        candidate["status"] = exc.message
        return candidate
    appliance = status.get("appliance") or {}
    candidate["snmp_supported"] = True
    appliance_model = appliance.get("model")
    if appliance_model and (not candidate.get("model") or _is_generic_printer_model(candidate.get("model"))):
        candidate["model"] = appliance_model
    candidate["serial"] = appliance.get("serial")
    candidate["ink_count"] = len(appliance.get("inkLevels") or [])
    candidate["lowest_ink_percent"] = appliance.get("lowestInkPercent")
    candidate["status"] = appliance.get("status") or "Ready"
    if _is_generic_printer_name(candidate.get("name")) or str(candidate.get("name") or "").lower() == "g6000 series":
        candidate["name"] = candidate.get("model") or appliance.get("systemName") or appliance.get("model") or candidate.get("name")
    return candidate


def _is_generic_printer_name(value: str | None) -> bool:
    return not value or bool(re.match(r"^Printer\s+\d{1,3}(?:\.\d{1,3}){3}$", value.strip()))


def _is_generic_printer_model(value: str | None) -> bool:
    return not value or value.strip().lower() in {"printer", "canon printer", "sawgrass printer"}


def _ipp_attribute_candidate(host: str) -> dict[str, Any] | None:
    for uri in (
        f"ipp://{host}/ipp/print",
        f"ipp://{host}/ipp",
        f"ipp://{host}/printers/{host}",
        f"ipp://{host}/",
    ):
        output = _command_output(["ipptool", "-tv", "-I", uri, "get-printer-attributes.test"], 2)
        if not re.search(r"status-code\s+=\s+successful-ok\b", output):
            continue
        model = _ipp_output_value(output, "printer-make-and-model")
        name = _ipp_output_value(output, "printer-name") or _ipp_output_value(output, "printer-info")
        guessed_model = _guess_model(" ".join(part for part in (model, name) if part))
        return {
            "host": host,
            "name": name or guessed_model or model,
            "model": guessed_model or model,
            "uri": uri,
        }
    return None


def _ipp_output_value(output: str, attribute: str) -> str | None:
    match = re.search(rf"\b{re.escape(attribute)}\s+\([^)]+\)\s+=\s+(.+)", output)
    if not match:
        return None
    return match.group(1).strip().strip('"') or None


def _resolve_host_address(host: str) -> str:
    clean_host = host.rstrip(".")
    try:
        ipaddress.ip_address(clean_host)
        return clean_host
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return clean_host
    for item in infos:
        address = item[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if isinstance(parsed, ipaddress.IPv4Address) and (parsed.is_private or parsed.is_link_local):
            return address
    return clean_host


def _clean_name(value: str) -> str:
    text = urllib.parse.unquote(value or "").replace("_", " ").strip()
    return re.sub(r"\s+", " ", text) or "Printer"


def _guess_model(value: str | None) -> str | None:
    text = (value or "").lower()
    if "magicard" in text and re.search(r"\b300\b", text):
        return "Magicard 300"
    if "sg500" in text or "sg 500" in text:
        return "Sawgrass SG500"
    if "g6020" in text or "g 6020" in text or "g-6020" in text:
        return "Canon G6020"
    if "canon" in text and "g6000" in text:
        return "Canon G6020"
    if "gp-4600s" in text or "gp 4600s" in text or "gp4600s" in text:
        return "Canon GP-4600S"
    if "imageprograf" in text and "4600" in text:
        return "Canon GP-4600S"
    if "sawgrass" in text:
        return "Sawgrass printer"
    if "canon" in text:
        return "Canon printer"
    if "magicard" in text:
        return "Magicard printer"
    return None


def _model_from_sys_descr(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";")[0].strip() or value


def _natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]
