import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import aiosqlite
from dotenv import load_dotenv

from app.models import Device
from app.schemas import DeviceCreate, DeviceUpdate


load_dotenv()

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/devices.db"))


def resolve_database_path() -> Path:
    if DATABASE_PATH.is_absolute():
        return DATABASE_PATH
    return Path.cwd() / DATABASE_PATH


async def get_connection() -> aiosqlite.Connection:
    db_path = resolve_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(db_path)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    return connection


@asynccontextmanager
async def connection_context() -> AsyncIterator[aiosqlite.Connection]:
    connection = await get_connection()
    try:
        yield connection
    finally:
        await connection.close()


def row_to_device(row: aiosqlite.Row) -> Device:
    return Device(
        id=row["id"],
        name=row["name"],
        brand=row["brand"],
        model=row["model"],
        host=row["host"],
        device_key=row["device_key"],
        device_uuid=row["device_uuid"],
        device_type=row["device_type"],
        channel=row["channel"],
        is_enabled=bool(row["is_enabled"]),
        last_state=row["last_state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def init_db() -> None:
    async with connection_context() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT 'meross',
                model TEXT,
                host TEXT NOT NULL,
                device_key TEXT,
                device_uuid TEXT,
                device_type TEXT,
                channel INTEGER DEFAULT 0,
                is_enabled INTEGER DEFAULT 1,
                last_state TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await db.commit()


async def list_devices() -> list[Device]:
    async with connection_context() as db:
        cursor = await db.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE")
        rows = await cursor.fetchall()
        return [row_to_device(row) for row in rows]


async def get_device(device_id: int) -> Optional[Device]:
    async with connection_context() as db:
        cursor = await db.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        row = await cursor.fetchone()
        return row_to_device(row) if row else None


async def create_device(payload: DeviceCreate) -> Device:
    async with connection_context() as db:
        cursor = await db.execute(
            """
            INSERT INTO devices (
                name, brand, model, host, device_key, device_uuid,
                device_type, channel, is_enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.brand,
                payload.model,
                payload.host,
                payload.device_key,
                payload.device_uuid,
                payload.device_type,
                payload.channel,
                int(payload.is_enabled),
            ),
        )
        await db.commit()
        created = await get_device(cursor.lastrowid)
        if created is None:
            raise RuntimeError("Device insert succeeded but the row could not be read back.")
        return created


async def find_device_by_uuid(device_uuid: str) -> Optional[Device]:
    async with connection_context() as db:
        cursor = await db.execute("SELECT * FROM devices WHERE device_uuid = ?", (device_uuid,))
        row = await cursor.fetchone()
        return row_to_device(row) if row else None


async def upsert_imported_device(payload: DeviceCreate) -> Device:
    existing = await find_device_by_uuid(payload.device_uuid) if payload.device_uuid else None
    if existing is None:
        return await create_device(payload)

    updated = await update_device(
        existing.id,
        DeviceUpdate(
            name=payload.name,
            brand=payload.brand,
            model=payload.model,
            host=payload.host,
            device_key=payload.device_key,
            device_uuid=payload.device_uuid,
            device_type=payload.device_type,
            channel=payload.channel,
            is_enabled=payload.is_enabled,
        ),
    )
    if updated is None:
        raise RuntimeError("Device update failed during imported device upsert.")
    return updated


async def update_device(device_id: int, payload: DeviceUpdate) -> Optional[Device]:
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return await get_device(device_id)

    assignments = []
    values: list[Any] = []
    for column, value in update_data.items():
        assignments.append(f"{column} = ?")
        values.append(int(value) if column == "is_enabled" and value is not None else value)

    assignments.append("updated_at = CURRENT_TIMESTAMP")
    values.append(device_id)

    async with connection_context() as db:
        cursor = await db.execute(
            f"UPDATE devices SET {', '.join(assignments)} WHERE id = ?",
            tuple(values),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
    return await get_device(device_id)


async def delete_device(device_id: int) -> bool:
    async with connection_context() as db:
        cursor = await db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        await db.commit()
        return cursor.rowcount > 0


async def save_last_state(device_id: int, state: str) -> None:
    async with connection_context() as db:
        await db.execute(
            "UPDATE devices SET last_state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (state, device_id),
        )
        await db.commit()
