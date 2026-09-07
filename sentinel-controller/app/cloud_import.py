import asyncio
import logging
import subprocess
from typing import Optional

from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager

from app import db
from app.schemas import (
    DeviceCreate,
    MerossCloudImportRequest,
    MerossCloudImportedDevice,
    MerossCloudImportResponse,
)


logger = logging.getLogger(__name__)


def _normalize_mac(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parts = value.lower().split(":")
    if len(parts) == 6 and all(1 <= len(part) <= 2 for part in parts):
        return ":".join(part.zfill(2) for part in parts)

    compact = "".join(ch for ch in value.lower() if ch.isalnum())
    if len(compact) != 12:
        return value.lower()
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _arp_ip_by_mac(mac_address: Optional[str]) -> Optional[str]:
    normalized = _normalize_mac(mac_address)
    if not normalized:
        return None

    try:
        output = subprocess.check_output(["arp", "-a"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None

    for line in output.splitlines():
        if normalized in _normalize_mac(line):
            start = line.find("(")
            end = line.find(")", start + 1)
            if start != -1 and end != -1:
                return line[start + 1:end]
    return None


def _channel_numbers(channels: object) -> list[int]:
    if not channels:
        return [0]

    numbers: list[int] = []
    for index, channel in enumerate(channels):
        if isinstance(channel, dict):
            value = channel.get("channel")
        else:
            value = getattr(channel, "id", None) or getattr(channel, "channel", None)

        try:
            numbers.append(int(value))
        except (TypeError, ValueError):
            numbers.append(index)

    return sorted(set(numbers)) or [0]


async def import_from_meross_cloud(payload: MerossCloudImportRequest) -> MerossCloudImportResponse:
    http_client = await MerossHttpClient.async_from_user_password(
        api_base_url=payload.api_base_url,
        email=payload.email,
        password=payload.password.get_secret_value(),
        mfa_code=payload.mfa_code,
    )
    manager: Optional[MerossManager] = None

    try:
        account_key = http_client.cloud_credentials.key
        cloud_devices = await http_client.async_list_devices()

        manager = MerossManager(http_client=http_client)
        await manager.async_init()
        try:
            await manager.async_device_discovery()
        except Exception:
            logger.exception("Meross manager discovery failed; continuing with cloud device list.")

        imported: list[MerossCloudImportedDevice] = []
        for cloud_device in cloud_devices:
            managed_matches = manager.find_devices(device_uuids=(cloud_device.uuid,)) if manager else []
            managed = managed_matches[0] if managed_matches else None

            if managed is not None:
                try:
                    await asyncio.wait_for(managed.async_update(), timeout=4)
                except Exception:
                    logger.info("Could not update Meross device %s during import.", cloud_device.uuid, exc_info=True)

            mac_address = _normalize_mac(getattr(managed, "mac_address", None))
            host = getattr(managed, "lan_ip", None) or _arp_ip_by_mac(mac_address)
            channels = _channel_numbers(getattr(cloud_device, "channels", None))

            saved_device = None
            note = None
            if payload.save_devices:
                if host:
                    saved_device = await db.upsert_imported_device(
                        DeviceCreate(
                            name=cloud_device.dev_name,
                            brand="meross",
                            model=cloud_device.device_type,
                            host=host,
                            device_key=account_key,
                            device_uuid=cloud_device.uuid,
                            device_type=cloud_device.device_type,
                            channel=channels[0],
                            is_enabled=True,
                        )
                    )
                else:
                    note = "Imported from cloud, but no LAN IP was discovered yet. Use router DHCP/ARP to set host."

            imported.append(
                MerossCloudImportedDevice(
                    id=saved_device.id if saved_device else None,
                    name=cloud_device.dev_name,
                    model=cloud_device.device_type,
                    host=host,
                    mac_address=mac_address,
                    device_uuid=cloud_device.uuid,
                    device_type=cloud_device.device_type,
                    channels=channels,
                    saved=bool(saved_device),
                    note=note,
                )
            )

        return MerossCloudImportResponse(
            imported=imported,
            account_key_available=bool(account_key),
            note="Meross email/password were used for this import only and were not stored.",
        )
    finally:
        if manager is not None:
            manager.close()
        await http_client.async_logout()
