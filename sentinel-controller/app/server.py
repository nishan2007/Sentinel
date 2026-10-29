"""Supervise Sentinel so web-requested restarts reload all application code."""
import argparse
import subprocess
import sys

import uvicorn

RESTART_EXIT_CODE = 75


def main():
    parser = argparse.ArgumentParser()
    # Sentinel is a LAN controller. Listen on every interface by default so the
    # dashboard and setup pages are reachable from another trusted LAN device.
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        while True:
            child = subprocess.Popen([sys.executable, "-m", "app.server", "--worker", *sys.argv[1:]])
            try:
                code = child.wait()
            except KeyboardInterrupt:
                # The foreground process group receives Ctrl+C, including Uvicorn.
                try:
                    child.wait(timeout=30)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    child.terminate()
                    child.wait()
                return 0
            if code != RESTART_EXIT_CODE:
                return code
    from app.main import app

    server = uvicorn.Server(uvicorn.Config(
        app, host=args.host, port=args.port,
        ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile,
    ))
    app.state.restart_requested = False

    def request_restart():
        app.state.restart_requested = True
        server.should_exit = True

    app.state.request_restart = request_restart
    server.run()
    return RESTART_EXIT_CODE if app.state.restart_requested else 0


if __name__ == "__main__":
    sys.exit(main())
