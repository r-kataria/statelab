"""Idempotent Anvil docker-compose lifecycle."""
from __future__ import annotations

import socket
import subprocess
import time as wall_time
from importlib import resources


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def _compose_path() -> str:
    return str(resources.files("statelab.infra") / "docker-compose.yml")


def ensure_docker_up(ports: list[int], deadline_seconds: int = 60) -> None:
    """Make sure every port responds, bringing up the Docker pair if needed.

    If a native Anvil (the supported path) is already listening on every port,
    this returns immediately and never touches Docker. Otherwise it brings up
    the bundled compose file and waits for the ports to open. Nodes are left
    running afterwards so repeated experiments reuse them; there is no automatic
    teardown.
    """
    if all(_is_port_open(p) for p in ports):
        return
    result = subprocess.run(
        ["docker", "compose", "-f", _compose_path(), "up", "-d"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "docker compose up failed:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    deadline = wall_time.time() + deadline_seconds
    while wall_time.time() < deadline:
        if all(_is_port_open(p) for p in ports):
            return
        wall_time.sleep(0.5)
    raise RuntimeError(f"anvil ports never opened within {deadline_seconds}s")
