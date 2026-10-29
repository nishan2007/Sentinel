import json
from typing import Any

from app import db


DEFAULT_SETTINGS = {
    "enabled": False,
    "bridge_name": "Sentinel Bridge",
    "port": 51826,
    "schema_version": 1,
}


async def init_homekit_db() -> None:
    async with db.connection_context() as connection:
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS homekit_settings (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                enabled INTEGER NOT NULL DEFAULT 0,
                bridge_name TEXT NOT NULL DEFAULT 'Sentinel Bridge',
                port INTEGER NOT NULL DEFAULT 51826,
                schema_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO homekit_settings(singleton) VALUES (1);

            CREATE TABLE IF NOT EXISTS homekit_accessories (
                device_id INTEGER PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
                aid INTEGER NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                profile TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {row["name"] for row in await (await connection.execute("PRAGMA table_info(homekit_accessories)")).fetchall()}
        if "temperature_display_units" not in columns:
            await connection.execute(
                "ALTER TABLE homekit_accessories ADD COLUMN temperature_display_units INTEGER NOT NULL DEFAULT 0"
            )
        await connection.commit()


async def get_settings() -> dict[str, Any]:
    async with db.connection_context() as connection:
        cursor = await connection.execute("SELECT * FROM homekit_settings WHERE singleton = 1")
        row = await cursor.fetchone()
    if not row:
        return dict(DEFAULT_SETTINGS)
    return {
        "enabled": bool(row["enabled"]),
        "bridge_name": row["bridge_name"],
        "port": row["port"],
        "schema_version": row["schema_version"],
        "updated_at": row["updated_at"],
    }


async def update_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {"enabled", "bridge_name", "port"}
    updates = {key: value for key, value in values.items() if key in allowed and value is not None}
    if updates:
        assignments = []
        params = []
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            params.append(int(value) if key == "enabled" else value)
        async with db.connection_context() as connection:
            await connection.execute(
                f"UPDATE homekit_settings SET {', '.join(assignments)}, updated_at = CURRENT_TIMESTAMP WHERE singleton = 1",
                tuple(params),
            )
            await connection.commit()
    return await get_settings()


async def ensure_accessory(device_id: int, profile: str | None) -> dict[str, Any]:
    async with db.connection_context() as connection:
        cursor = await connection.execute("SELECT * FROM homekit_accessories WHERE device_id = ?", (device_id,))
        row = await cursor.fetchone()
        if row is None:
            cursor = await connection.execute("SELECT COALESCE(MAX(aid), 1) + 1 FROM homekit_accessories")
            aid = max(2, int((await cursor.fetchone())[0]))
            if aid == 7:
                aid += 1
            await connection.execute(
                "INSERT INTO homekit_accessories(device_id, aid, enabled, profile) VALUES (?, ?, 1, ?)",
                (device_id, aid, profile),
            )
            await connection.commit()
        elif profile is not None and row["profile"] != profile:
            # Keep automatically detected profiles current as integrations gain
            # richer HomeKit mappings (for example, an AC becoming a thermostat).
            await connection.execute(
                "UPDATE homekit_accessories SET profile = ?, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
                (profile, device_id),
            )
            await connection.commit()
    return await get_accessory(device_id)


async def get_accessory(device_id: int) -> dict[str, Any] | None:
    async with db.connection_context() as connection:
        cursor = await connection.execute("SELECT * FROM homekit_accessories WHERE device_id = ?", (device_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


async def list_accessories() -> list[dict[str, Any]]:
    async with db.connection_context() as connection:
        cursor = await connection.execute(
            """SELECT h.*, d.name, d.brand, d.model, d.device_type, d.is_enabled AS device_enabled
               FROM homekit_accessories h JOIN devices d ON d.id = h.device_id
               ORDER BY d.name COLLATE NOCASE"""
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def update_accessory(device_id: int, *, enabled: bool | None = None, profile: str | None = None) -> dict[str, Any] | None:
    values = {}
    if enabled is not None:
        values["enabled"] = int(enabled)
    if profile is not None:
        values["profile"] = profile
    if values:
        assignments = [f"{key} = ?" for key in values]
        async with db.connection_context() as connection:
            await connection.execute(
                f"UPDATE homekit_accessories SET {', '.join(assignments)}, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
                (*values.values(), device_id),
            )
            await connection.commit()
    return await get_accessory(device_id)


async def set_error(device_id: int, error: str | None) -> None:
    async with db.connection_context() as connection:
        await connection.execute(
            "UPDATE homekit_accessories SET last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
            (error, device_id),
        )
        await connection.commit()


async def set_temperature_display_units(device_id: int, units: int) -> None:
    await update_accessory_temperature_units(device_id, units)


async def update_accessory_temperature_units(device_id: int, units: int) -> None:
    if units not in {0, 1}:
        raise ValueError("Temperature display units must be 0 (Celsius) or 1 (Fahrenheit).")
    async with db.connection_context() as connection:
        await connection.execute(
            "UPDATE homekit_accessories SET temperature_display_units = ?, updated_at = CURRENT_TIMESTAMP WHERE device_id = ?",
            (units, device_id),
        )
        await connection.commit()
