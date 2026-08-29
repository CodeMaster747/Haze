from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from haze.api.app import create_app
from haze.config import Config

TEST_PORT = 7433
TEST_TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def cfg() -> Config:
    return Config(
        node_name="test-node",
        api_port=TEST_PORT,
        node_port=8443,
        beacon_port=47654,
        dashboard_token=TEST_TOKEN,
    )


@pytest.fixture
def client(cfg: Config):
    # TestClient runs the lifespan, which starts the telemetry hub, so these
    # tests exercise the real sampler rather than a stub.
    with TestClient(create_app(cfg, TEST_PORT)) as c:
        yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def own_origin() -> str:
    return f"http://127.0.0.1:{TEST_PORT}"
