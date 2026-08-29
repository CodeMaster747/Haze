"""The loopback API's two auth gates.

These are not hardening tests, they are correctness tests for the security
boundary.  The agent can execute subprocesses, and loopback is reachable from
any web page the user has open -- Firefox today lets an arbitrary https page
open ws://127.0.0.1 with no prompt at all, and WebSocket upgrades carry no CORS
preflight.  If these tests fail, any site the user visits can drive their
compute cluster.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import TEST_PORT, TEST_TOKEN

EVIL = "https://evil.example.com"


# --- HTTP -------------------------------------------------------------------

def test_api_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 401


def test_api_rejects_a_wrong_token(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_api_accepts_bearer_token(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get("/api/v1/health", headers=auth)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_accepts_query_token(client: TestClient) -> None:
    assert client.get(f"/api/v1/health?t={TEST_TOKEN}").status_code == 200


def test_api_accepts_own_origin(client: TestClient, auth: dict[str, str], own_origin: str) -> None:
    r = client.get("/api/v1/health", headers={**auth, "Origin": own_origin})
    assert r.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        EVIL,
        "http://localhost:9999",             # right host, wrong port
        f"http://127.0.0.1:{TEST_PORT + 1}",  # off by one port
        f"https://127.0.0.1:{TEST_PORT}",     # right authority, wrong scheme
        "null",                               # sandboxed iframe / file://
    ],
)
def test_api_rejects_foreign_origins_even_with_a_valid_token(
    client: TestClient, auth: dict[str, str], origin: str
) -> None:
    r = client.get("/api/v1/health", headers={**auth, "Origin": origin})
    assert r.status_code == 403, f"{origin} was allowed"


def test_no_cors_header_is_ever_emitted(client: TestClient, auth: dict[str, str], own_origin: str) -> None:
    # A CORS grant on this server would hand cross-origin read access to exactly
    # the attacker the origin check exists to keep out.
    r = client.get("/api/v1/health", headers={**auth, "Origin": own_origin})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_security_headers_present(client: TestClient) -> None:
    h = client.get("/").headers
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"


# --- WebSocket --------------------------------------------------------------
# The upgrade carries no CORS preflight, so the Origin check here is the ONLY
# thing standing between a foreign page and this node's telemetry.

def _sub(token: str) -> list[str]:
    return ["haze.v1", f"haze.token.{token}"]


def test_ws_requires_a_token(client: TestClient) -> None:
    # starlette raises when the server closes before accept()
    with pytest.raises(Exception), client.websocket_connect("/ws"):  # noqa: B017
        pass


def test_ws_rejects_a_wrong_token(client: TestClient) -> None:
    with pytest.raises(Exception), client.websocket_connect("/ws", subprotocols=_sub("wrong")):  # noqa: B017
        pass


def test_ws_accepts_valid_token_and_own_origin(client: TestClient, own_origin: str) -> None:
    with client.websocket_connect(
        "/ws", subprotocols=_sub(TEST_TOKEN), headers={"Origin": own_origin}
    ) as socket:
        first = socket.receive_json()
    assert first["type"] == "snapshot"
    assert first["data"]["cpu"]["cores"] >= 1


def test_ws_accepts_native_client_with_no_origin(client: TestClient) -> None:
    with client.websocket_connect("/ws", subprotocols=_sub(TEST_TOKEN)) as socket:
        assert socket.receive_json()["type"] == "snapshot"


def test_ws_accepts_token_via_query_param(client: TestClient) -> None:
    with client.websocket_connect(f"/ws?t={TEST_TOKEN}") as socket:
        assert socket.receive_json()["type"] == "snapshot"


@pytest.mark.parametrize("origin", [EVIL, f"http://127.0.0.1:{TEST_PORT + 1}", "null"])
def test_ws_rejects_foreign_origin_even_with_a_valid_token(client: TestClient, origin: str) -> None:
    """THE P0 CASE.

    A page on another origin that has somehow learned the token must still be
    refused at the upgrade.
    """
    with pytest.raises(Exception), client.websocket_connect(  # noqa: B017
        "/ws", subprotocols=_sub(TEST_TOKEN), headers={"Origin": origin}
    ):
        pass


def test_ws_never_echoes_the_token_bearing_subprotocol(client: TestClient) -> None:
    # The negotiated subprotocol is visible to the page and in devtools; echoing
    # `haze.token.<secret>` back would leak the token into both.
    with client.websocket_connect("/ws", subprotocols=_sub(TEST_TOKEN)) as socket:
        assert socket.accepted_subprotocol == "haze.v1"
