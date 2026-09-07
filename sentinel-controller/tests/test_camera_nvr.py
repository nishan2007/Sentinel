import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import camera_db, camera_service, db
from app.schemas import DeviceCreate


class CameraValidationTests(unittest.TestCase):
    def test_recordings_use_one_minute_segments(self):
        self.assertEqual(camera_service.RECORDING_SEGMENT_SECONDS, 60)

    def test_accepts_local_rtsp_and_strips_embedded_credentials(self):
        cleaned = camera_service.validate_stream_url("rtsp://admin:secret@127.0.0.1:8554/live", "127.0.0.1")
        self.assertEqual(cleaned, "rtsp://127.0.0.1:8554/live")
        self.assertNotIn("secret", cleaned)

    def test_rejects_non_rtsp_urls(self):
        with self.assertRaises(camera_service.CameraServiceError):
            camera_service.validate_stream_url("https://127.0.0.1/video")

    def test_live_path_cannot_escape_camera_folder(self):
        with self.assertRaises(camera_service.CameraServiceError):
            camera_service.safe_live_file(10, "../secret")

    def test_recorder_errors_redact_credentials(self):
        camera = {"username": "admin", "password": "very-secret", "main_stream_url": "rtsp://127.0.0.1/live"}
        message = "failed rtsp://admin:very-secret@127.0.0.1/live for admin very-secret"
        redacted = camera_service._redact(message, camera)
        self.assertNotIn("very-secret", redacted)
        self.assertNotIn("admin", redacted)

    def test_routed_discovery_keeps_vpn_route_and_skips_link_networks(self):
        routes = """Destination Gateway Flags Netif\n10.1.1/24 10.191.61.69 UGSc feth1285\n10.191.61/24 link#20 UC feth1285\n172.20.40/23 link#15 UC en0\n"""
        with patch("app.camera_service.shutil.which", return_value=None), patch(
            "app.camera_service.subprocess.run", return_value=SimpleNamespace(stdout=routes)
        ), patch.dict("os.environ", {"SENTINEL_CAMERA_SUBNETS": ""}):
            self.assertEqual(camera_service.routed_private_subnets(), ["10.1.1.0/24"])

    def test_segment_start_uses_ffmpeg_filename_time(self):
        started = camera_service._segment_started_at(Path("20260722-143719.mp4"), 0, 12.03)
        parsed = datetime.fromisoformat(started)
        self.assertEqual(parsed.astimezone().strftime("%Y%m%d-%H%M%S"), "20260722-143719")

    def test_segment_start_falls_back_from_finalized_time(self):
        started = camera_service._segment_started_at(Path("legacy.mp4"), 100.0, 12.0)
        self.assertEqual(datetime.fromisoformat(started).timestamp(), 88.0)


class CameraDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db.DATABASE_PATH
        db.DATABASE_PATH = Path(self.temp.name) / "devices.db"
        await db.init_db()
        await camera_db.init_camera_db()

    async def asyncTearDown(self):
        db.DATABASE_PATH = self.old_path
        self.temp.cleanup()

    async def test_camera_api_shape_redacts_streams_and_password(self):
        device = await db.create_device(DeviceCreate(
            name="Test camera", brand="ip-camera", host="127.0.0.1", device_type="camera"
        ))
        camera = await camera_db.create_camera(device.id, {
            "username": "admin", "password": "top-secret",
            "main_stream_url": "rtsp://127.0.0.1/main", "sub_stream_url": None,
            "recording_enabled": True, "audio_enabled": True,
        })
        self.assertNotIn("password", camera)
        self.assertNotIn("main_stream_url", camera)
        secret = await camera_db.get_camera(camera["id"], include_secrets=True)
        self.assertEqual(secret["password"], "top-secret")

    async def test_storage_cleanup_only_removes_indexed_recordings(self):
        device = await db.create_device(DeviceCreate(
            name="Cleanup camera", brand="ip-camera", host="127.0.0.1", device_type="camera"
        ))
        camera = await camera_db.create_camera(device.id, {
            "main_stream_url": "rtsp://127.0.0.1/main", "recording_enabled": False,
        })
        root = Path(self.temp.name) / "recordings"
        folder = root / str(camera["id"])
        folder.mkdir(parents=True)
        recording = folder / "recording.mp4"
        unrelated = root / "keep-me.txt"
        recording.write_bytes(b"video")
        unrelated.write_text("user file")
        await camera_db.update_settings(str(root), 1, 1)
        async with db.connection_context() as conn:
            await conn.execute(
                "INSERT INTO recording_segments(camera_id, relative_path, started_at, size_bytes) VALUES(?, ?, ?, ?)",
                (camera["id"], f"{camera['id']}/recording.mp4", "2026-01-01T00:00:00+00:00", 5),
            )
            await conn.commit()
        usage = type("Usage", (), {"total": 100, "used": 99, "free": 0})()
        with patch("app.camera_service.shutil.disk_usage", return_value=usage):
            await camera_service.enforce_storage_limits()
        self.assertFalse(recording.exists())
        self.assertTrue(unrelated.exists())

    async def test_segment_upsert_replaces_placeholder_duration(self):
        device = await db.create_device(DeviceCreate(
            name="Duration camera", brand="ip-camera", host="127.0.0.1", device_type="camera"
        ))
        camera = await camera_db.create_camera(device.id, {
            "main_stream_url": "rtsp://127.0.0.1/main", "recording_enabled": False,
        })
        await camera_db.upsert_segment(
            camera["id"], f"{camera['id']}/clip.mp4", "2026-01-01T00:00:00+00:00", 10.0, 100,
        )
        await camera_db.upsert_segment(
            camera["id"], f"{camera['id']}/clip.mp4", "2026-01-01T00:00:00+00:00", 12.034, 120,
        )
        segments = await camera_db.list_segments(camera["id"])
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]["duration_seconds"], 12.034)
        self.assertEqual(segments[0]["size_bytes"], 120)


if __name__ == "__main__":
    unittest.main()
