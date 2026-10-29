import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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

    def test_routed_discovery_keeps_vpn_and_connected_mac_networks(self):
        routes = """Destination Gateway Flags Netif\n10.1.1/24 10.191.61.69 UGSc feth1285\n10.191.61/24 link#20 UC feth1285\n172.20.40/23 link#15 UC en0\n"""
        with patch("app.camera_service.shutil.which", return_value=None), patch(
            "app.camera_service.subprocess.run", return_value=SimpleNamespace(stdout=routes)
        ), patch.dict("os.environ", {"SENTINEL_CAMERA_SUBNETS": ""}), patch("os.name", "posix"):
            self.assertEqual(camera_service.routed_private_subnets(), ["10.1.1.0/24", "10.191.61.0/24", "172.20.40.0/23"])

    def test_windows_routed_discovery_keeps_vpn_and_on_link_networks(self):
        routes = """Network Destination Netmask Gateway Interface Metric
0.0.0.0 0.0.0.0 192.168.1.1 192.168.1.20 25
10.1.1.0 255.255.255.0 10.191.61.69 10.191.61.70 5
10.191.61.0 255.255.255.0 On-link 10.191.61.70 25
172.20.40.0 255.255.254.0 On-link 172.20.40.10 25
172.20.40.10 255.255.255.255 On-link 172.20.40.10 25
127.0.0.0 255.0.0.0 On-link 127.0.0.1 331
224.0.0.0 240.0.0.0 On-link 172.20.40.10 25
"""
        with patch("app.camera_service.subprocess.run", return_value=SimpleNamespace(stdout=routes)) as run, patch.dict(
            "os.environ", {"SENTINEL_CAMERA_SUBNETS": ""}
        ), patch("os.name", "nt"):
            self.assertEqual(camera_service.routed_private_subnets(), ["10.1.1.0/24", "10.191.61.0/24", "172.20.40.0/23"])
            self.assertEqual(run.call_args.args[0], ["route", "print", "-4"])

    def test_linux_discovery_keeps_connected_network_and_deduplicates(self):
        routes = "default via 10.1.1.1 dev eth0\n10.1.1.0/24 dev eth0 proto kernel src 10.1.1.149\n192.168.50.0/24 via 10.1.1.1 dev eth0\n10.0.0.0/8 dev tun0\n"
        with patch("app.camera_service.shutil.which", return_value="/usr/bin/ip"), patch(
            "app.camera_service.subprocess.run", return_value=SimpleNamespace(stdout=routes)
        ), patch.dict("os.environ", {"SENTINEL_CAMERA_SUBNETS": "10.1.1.0/24"}), patch("os.name", "posix"):
            self.assertEqual(camera_service.routed_private_subnets(), ["10.1.1.0/24", "192.168.50.0/24"])

    def test_segment_start_uses_ffmpeg_filename_time(self):
        started = camera_service._segment_started_at(Path("20260722-143719.mp4"), 0, 12.03)
        parsed = datetime.fromisoformat(started)
        self.assertEqual(parsed.astimezone().strftime("%Y%m%d-%H%M%S"), "20260722-143719")

    def test_segment_start_falls_back_from_finalized_time(self):
        started = camera_service._segment_started_at(Path("legacy.mp4"), 100.0, 12.0)
        self.assertEqual(datetime.fromisoformat(started).timestamp(), 88.0)


class CameraDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_multicast_excludes_printers_and_computers(self):
        def service(host, types, path):
            return SimpleNamespace(getXAddrs=lambda: [f"http://{host}{path}"],
                                   getTypes=lambda: types, getScopes=lambda: [])
        discovery = Mock()
        discovery.searchServices.return_value = [
            service("10.1.1.13", ["PrintDeviceType"], "/wsd/mex"),
            service("10.1.1.100", ["Computer"], "/metadata"),
            service("10.1.1.51", ["http://www.onvif.org/ver10/network/wsdl:NetworkVideoTransmitter"], "/device"),
            service("10.1.1.99", [], "/onvif/device_service"),
        ]
        with patch("wsdiscovery.discovery.ThreadedWSDiscovery", return_value=discovery):
            result = await camera_service.discover_onvif(scan_routed_subnets=False)
        self.assertEqual([c["host"] for c in result["cameras"]], ["10.1.1.51", "10.1.1.99"])
        discovery.stop.assert_called_once()

    async def test_multicast_failure_still_scans_connected_lan(self):
        cameras = [{"host": "10.1.1.51", "onvif_port": 80}, {"host": "10.1.1.99", "rtsp_port": 554}]
        with patch("app.camera_service.asyncio.to_thread", side_effect=OSError("Multicast unavailable")), patch(
            "app.camera_service.routed_private_subnets", return_value=["10.1.1.0/24"]
        ), patch("app.camera_service._scan_routed_subnets", new_callable=AsyncMock, return_value=cameras) as scan:
            result = await camera_service.discover_onvif()
        self.assertEqual(result["cameras"], cameras)
        self.assertEqual(result["scanned_subnets"], ["10.1.1.0/24"])
        self.assertIsNotNone(result["multicast_error"])
        scan.assert_awaited_once_with(["10.1.1.0/24"], 0.6)


class CameraPtzTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuous_move_sends_pan_tilt_and_zoom(self):
        service = Mock()
        with patch("app.camera_service._onvif_ptz", return_value=(service, "profile-token", Mock())):
            await camera_service.ptz_move({"host": "10.1.1.50"}, 0.5, -0.25, 0.75)
        service.ContinuousMove.assert_called_once_with({
            "ProfileToken": "profile-token",
            "Velocity": {"PanTilt": {"x": 0.5, "y": -0.25}, "Zoom": {"x": 0.75}},
        })

    async def test_stop_halts_pan_tilt_and_zoom(self):
        service = Mock()
        with patch("app.camera_service._onvif_ptz", return_value=(service, "profile-token", Mock())):
            await camera_service.ptz_stop({"host": "10.1.1.50"})
        service.Stop.assert_called_once_with({
            "ProfileToken": "profile-token", "PanTilt": True, "Zoom": True,
        })


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

    async def test_camera_can_be_found_by_host_case_insensitively(self):
        device = await db.create_device(DeviceCreate(
            name="Existing camera", brand="ip-camera", host="Camera.Local", device_type="camera"
        ))
        created = await camera_db.create_camera(device.id, {
            "main_stream_url": "rtsp://camera.local/main", "recording_enabled": False,
        })
        found = await camera_db.get_camera_by_host("  camera.local  ")
        self.assertEqual(found["id"], created["id"])

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
