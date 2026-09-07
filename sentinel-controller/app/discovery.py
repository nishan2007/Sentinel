import asyncio
import ipaddress
import os
import socket
from contextlib import closing
from typing import Optional

from dotenv import load_dotenv


load_dotenv()

DEFAULT_SCAN_TIMEOUT_SECONDS = float(os.getenv("MEROSS_SCAN_CONNECT_TIMEOUT_SECONDS", "0.35"))


def default_subnet() -> str:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            ip_address = sock.getsockname()[0]
        except OSError:
            ip_address = "127.0.0.1"

    parts = ip_address.split(".")
    if len(parts) != 4:
        return "127.0.0.0/24"
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


async def _port_open(host: str, port: int, timeout_seconds: float) -> Optional[str]:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_seconds,
        )
        writer.close()
        await writer.wait_closed()
        return host
    except (asyncio.TimeoutError, OSError):
        return None


async def scan_network(
    subnet: Optional[str] = None,
    port: int = 80,
    timeout_seconds: Optional[float] = None,
) -> dict[str, object]:
    subnet = subnet or default_subnet()
    timeout_seconds = timeout_seconds or DEFAULT_SCAN_TIMEOUT_SECONDS
    network = ipaddress.ip_network(subnet, strict=False)

    tasks = [
        _port_open(str(host), port, timeout_seconds)
        for host in network.hosts()
    ]
    results = await asyncio.gather(*tasks)
    hosts = sorted(host for host in results if host is not None)
    return {"subnet": str(network), "port": port, "hosts": hosts}
