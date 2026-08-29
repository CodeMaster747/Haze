from __future__ import annotations

from pathlib import Path

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
def client(cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # HAZE_HOME redirects all agent state into the test's tmp_path, so the suite
    # never touches (or is influenced by) the developer's real ~/.haze.
    monkeypatch.setenv("HAZE_HOME", str(tmp_path / "haze"))
    # serve_peers=False: no LAN listener. The API tests do not need one, and
    # binding a fixed port would make the suite fail whenever a real agent is
    # running on the same machine.
    with TestClient(create_app(cfg, TEST_PORT, serve_peers=False)) as c:
        yield c


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def own_origin() -> str:
    return f"http://127.0.0.1:{TEST_PORT}"
