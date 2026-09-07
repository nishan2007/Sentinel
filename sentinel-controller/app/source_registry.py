import re
from dataclasses import dataclass
from typing import Iterable

from app.models import Device
from app.schemas import DeviceUpdate
from app import db


NATIVE_SOURCES = {"meross", "nest", "ring", "yale"}
SOURCE_PRIORITY = {
    "meross": 100,
    "nest": 100,
    "ring": 100,
    "yale": 100,
    "smartthings": 50,
}


@dataclass(frozen=True)
class Overlap:
    device: Device
    reason: str


def normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def source_priority(source: str | None) -> int:
    return SOURCE_PRIORITY.get((source or "").lower(), 10)


def native_source_from_text(*parts: str | None) -> str | None:
    text = " ".join(part or "" for part in parts).lower()
    for source in ("meross", "nest", "ring", "yale"):
        if source in text:
            return source
    if "august" in text:
        return "yale"
    return None


def device_identity(device: Device) -> set[str]:
    values = {
        device.device_uuid,
        device.host,
        normalize_name(device.name),
    }
    if device.host and ":" in device.host:
        values.add(device.host.split(":", 1)[1])
    return {value for value in values if value}


def candidate_identity(name: str, external_id: str | None, host: str | None = None) -> set[str]:
    values = {external_id, host, normalize_name(name)}
    if host and ":" in host:
        values.add(host.split(":", 1)[1])
    return {value for value in values if value}


def find_overlaps(
    existing: Iterable[Device],
    *,
    source: str,
    name: str,
    external_id: str | None,
    host: str | None = None,
    only_lower_priority: bool = False,
) -> list[Overlap]:
    candidate_values = candidate_identity(name, external_id, host)
    matches: list[Overlap] = []
    for device in existing:
        if only_lower_priority and source_priority(device.brand) >= source_priority(source):
            continue
        if not candidate_values.intersection(device_identity(device)):
            continue

        reason = "same external id already exists" if external_id and external_id in device_identity(device) else "normalized name matches"
        matches.append(Overlap(device=device, reason=reason))
    return matches


async def disable_lower_priority_overlaps(
    *,
    source: str,
    name: str,
    external_id: str | None,
    host: str | None = None,
) -> list[Overlap]:
    existing = await db.list_devices()
    overlaps = find_overlaps(
        existing,
        source=source,
        name=name,
        external_id=external_id,
        host=host,
        only_lower_priority=True,
    )
    disabled: list[Overlap] = []
    for overlap in overlaps:
        if overlap.device.brand.lower() == source.lower() or not overlap.device.is_enabled:
            continue
        await db.update_device(overlap.device.id, DeviceUpdate(is_enabled=False))
        disabled.append(overlap)
    return disabled
