import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request
from starlette.datastructures import State

from app import server, system_api


class RestartTests(unittest.IsolatedAsyncioTestCase):
    def request(self, headers=None, callback=None):
        state = State()
        if callback:
            state.request_restart = callback
        return Request({"type": "http", "method": "POST", "scheme": "http",
                        "path": "/api/system/restart", "root_path": "", "query_string": b"",
                        "server": ("localhost", 8088), "headers": headers or [],
                        "app": SimpleNamespace(state=state)})

    async def test_restart_runs_after_response_and_only_once(self):
        callback = Mock()
        request = self.request([(b"x-sentinel-action", b"restart"),
                                (b"origin", b"http://localhost:8088")], callback)
        tasks = BackgroundTasks()
        result = await system_api.restart(request, tasks)
        await system_api.restart(request, tasks)
        self.assertEqual(result["instance_id"], system_api.INSTANCE_ID)
        callback.assert_not_called()
        await tasks()
        callback.assert_called_once()

    async def test_rejects_cross_origin_and_plain_form_requests(self):
        for headers in [[], [(b"x-sentinel-action", b"restart"), (b"origin", b"https://other.test")]]:
            callback = Mock()
            with self.assertRaises(HTTPException) as error:
                await system_api.restart(self.request(headers, callback), BackgroundTasks())
            self.assertEqual(error.exception.status_code, 403)
            callback.assert_not_called()

    async def test_unmanaged_server_is_not_stopped(self):
        request = self.request([(b"x-sentinel-action", b"restart")])
        with self.assertRaises(HTTPException) as error:
            await system_api.restart(request, BackgroundTasks())
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse((await system_api.system_status(request))["restart_supported"])

    def test_supervisor_relaunches_only_for_requested_restart(self):
        first, second = Mock(), Mock()
        first.wait.return_value = server.RESTART_EXIT_CODE
        second.wait.return_value = 0
        with patch("sys.argv", ["server", "--port", "8099"]), patch(
            "app.server.subprocess.Popen", side_effect=[first, second]
        ) as spawn:
            self.assertEqual(server.main(), 0)
        self.assertEqual(spawn.call_count, 2)
        self.assertEqual(spawn.call_args_list[0], spawn.call_args_list[1])

    def test_supervisor_does_not_loop_on_crash(self):
        child = Mock()
        child.wait.return_value = 1
        with patch("sys.argv", ["server"]), patch("app.server.subprocess.Popen", return_value=child) as spawn:
            self.assertEqual(server.main(), 1)
        spawn.assert_called_once()
