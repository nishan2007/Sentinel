from pathlib import Path
from typing import Any

from app import db


async def init_camera_db() -> None:
    async with db.connection_context() as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS camera_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
                username TEXT,
                password TEXT,
                main_stream_url TEXT NOT NULL,
                sub_stream_url TEXT,
                recording_enabled INTEGER NOT NULL DEFAULT 1,
                audio_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS recording_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL REFERENCES camera_profiles(id) ON DELETE CASCADE,
                relative_path TEXT NOT NULL UNIQUE,
                started_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL DEFAULT 10,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_recording_segments_camera_time
              ON recording_segments(camera_id, started_at);
            CREATE TABLE IF NOT EXISTS camera_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                recording_root TEXT NOT NULL,
                capacity_bytes INTEGER,
                reserve_bytes INTEGER NOT NULL DEFAULT 10737418240,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await conn.execute(
            "INSERT OR IGNORE INTO camera_settings(singleton, recording_root) VALUES(1, ?)",
            (str(Path("data") / "recordings"),),
        )
        await conn.commit()


def _camera_out(row: Any) -> dict:
    return {
        "id": row["id"], "device_id": row["device_id"], "name": row["name"],
        "host": row["host"], "model": row["model"], "username": row["username"],
        "main_stream_configured": bool(row["main_stream_url"]),
        "sub_stream_configured": bool(row["sub_stream_url"]),
        "recording_enabled": bool(row["recording_enabled"]),
        "audio_enabled": bool(row["audio_enabled"]), "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_cameras(*, include_secrets: bool = False) -> list[dict]:
    async with db.connection_context() as conn:
        cursor = await conn.execute(
            """SELECT cp.*, d.name, d.host, d.model FROM camera_profiles cp
               JOIN devices d ON d.id = cp.device_id ORDER BY d.name COLLATE NOCASE"""
        )
        rows = await cursor.fetchall()
    if include_secrets:
        return [dict(row) for row in rows]
    return [_camera_out(row) for row in rows]


async def get_camera(camera_id: int, *, include_secrets: bool = False) -> dict | None:
    async with db.connection_context() as conn:
        cursor = await conn.execute(
            """SELECT cp.*, d.name, d.host, d.model FROM camera_profiles cp
               JOIN devices d ON d.id = cp.device_id WHERE cp.id = ?""", (camera_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return dict(row) if include_secrets else _camera_out(row)


async def get_camera_by_device(device_id: int, *, include_secrets: bool = False) -> dict | None:
    async with db.connection_context() as conn:
        cursor = await conn.execute(
            """SELECT cp.*, d.name, d.host, d.model FROM camera_profiles cp
               JOIN devices d ON d.id = cp.device_id WHERE cp.device_id = ?""", (device_id,),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return dict(row) if include_secrets else _camera_out(row)


async def create_camera(device_id: int, payload: dict) -> dict:
    async with db.connection_context() as conn:
        cursor = await conn.execute(
            """INSERT INTO camera_profiles(device_id, username, password, main_stream_url,
               sub_stream_url, recording_enabled, audio_enabled) VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (device_id, payload.get("username"), payload.get("password"), payload["main_stream_url"],
             payload.get("sub_stream_url"), int(payload.get("recording_enabled", True)),
             int(payload.get("audio_enabled", True))),
        )
        await conn.commit()
        camera_id = cursor.lastrowid
    return await get_camera(camera_id)


async def update_camera(camera_id: int, payload: dict) -> dict | None:
    camera = await get_camera(camera_id, include_secrets=True)
    if not camera:
        return None
    device_fields = {k: payload.pop(k) for k in ("name", "host", "model") if k in payload}
    if device_fields:
        from app.schemas import DeviceUpdate
        await db.update_device(camera["device_id"], DeviceUpdate(**device_fields))
    if payload:
        values = []
        assignments = []
        for key, value in payload.items():
            assignments.append(f"{key} = ?")
            values.append(int(value) if key in {"recording_enabled", "audio_enabled"} else value)
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(camera_id)
        async with db.connection_context() as conn:
            await conn.execute(f"UPDATE camera_profiles SET {', '.join(assignments)} WHERE id = ?", values)
            await conn.commit()
    return await get_camera(camera_id)


async def delete_camera(camera_id: int) -> bool:
    camera = await get_camera(camera_id, include_secrets=True)
    if not camera:
        return False
    async with db.connection_context() as conn:
        await conn.execute("DELETE FROM camera_profiles WHERE id = ?", (camera_id,))
        await conn.commit()
    await db.delete_device(camera["device_id"])
    return True


async def get_settings() -> dict:
    async with db.connection_context() as conn:
        cursor = await conn.execute("SELECT * FROM camera_settings WHERE singleton = 1")
        return dict(await cursor.fetchone())


async def update_settings(recording_root: str, capacity_bytes: int | None, reserve_bytes: int) -> dict:
    async with db.connection_context() as conn:
        await conn.execute(
            """UPDATE camera_settings SET recording_root = ?, capacity_bytes = ?, reserve_bytes = ?,
               updated_at = CURRENT_TIMESTAMP WHERE singleton = 1""",
            (recording_root, capacity_bytes, reserve_bytes),
        )
        await conn.commit()
    return await get_settings()


async def upsert_segment(
    camera_id: int,
    relative_path: str,
    started_at: str,
    duration_seconds: float,
    size_bytes: int,
) -> None:
    async with db.connection_context() as conn:
        await conn.execute(
            """INSERT INTO recording_segments(
                   camera_id, relative_path, started_at, duration_seconds, size_bytes
               ) VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(relative_path) DO UPDATE SET
                   camera_id = excluded.camera_id,
                   started_at = excluded.started_at,
                   duration_seconds = excluded.duration_seconds,
                   size_bytes = excluded.size_bytes""",
            (camera_id, relative_path, started_at, max(0.001, duration_seconds), size_bytes),
        )
        await conn.commit()


async def list_segments(camera_id: int, start: str | None = None, end: str | None = None) -> list[dict]:
    clauses, values = ["camera_id = ?"], [camera_id]
    if start:
        clauses.append("started_at >= ?"); values.append(start)
    if end:
        clauses.append("started_at <= ?"); values.append(end)
    async with db.connection_context() as conn:
        cursor = await conn.execute(
            f"SELECT * FROM recording_segments WHERE {' AND '.join(clauses)} ORDER BY started_at", values,
        )
        return [dict(row) for row in await cursor.fetchall()]


async def oldest_segments() -> list[dict]:
    async with db.connection_context() as conn:
        cursor = await conn.execute("SELECT * FROM recording_segments ORDER BY started_at")
        return [dict(row) for row in await cursor.fetchall()]


async def delete_segment(segment_id: int) -> None:
    async with db.connection_context() as conn:
        await conn.execute("DELETE FROM recording_segments WHERE id = ?", (segment_id,))
        await conn.commit()
