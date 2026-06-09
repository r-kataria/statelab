import socket

import pytest


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


@pytest.fixture(scope="session")
def anvil_pair():
    """Ensure the Anvil pair is up for integration tests."""
    from statelab.core.docker import ensure_docker_up
    ensure_docker_up([8545, 8546])
    assert _port_open(8545) and _port_open(8546)
    yield
