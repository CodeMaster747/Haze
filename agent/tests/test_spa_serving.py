"""The agent serves the dashboard bundle, and only the dashboard bundle.

The SPA catch-all route takes an arbitrary path from the URL and turns it into a
filesystem lookup, which is the classic shape of a path-traversal bug. These
tests exist because the file one directory up from the bundle is the agent's
0600 config -- the one holding the dashboard token that gates process execution
on this machine.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from haze.api.app import WEBUI_DIR

pytestmark = pytest.mark.skipif(
    not (WEBUI_DIR / "index.html").is_file(),
    reason="dashboard bundle not built; run `make build-web`",
)


def test_root_serves_the_spa(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


def test_unknown_route_falls_back_to_index(client: TestClient) -> None:
    """Client-side routes must deep-link, so an unknown path is index.html."""
    r = client.get("/jobs/abc123")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


def test_api_is_not_shadowed_by_the_catch_all(client: TestClient) -> None:
    # If route ordering regressed, /api would fall through to the SPA and
    # return 200 + HTML instead of enforcing auth.
    r = client.get("/api/v1/health")
    assert r.status_code == 401


def test_an_unknown_api_path_is_a_404_not_the_dashboard(
    client: TestClient, auth: dict[str, str]
) -> None:
    """A mistyped API path used to return 200 + index.html, which a client then
    failed to parse as JSON somewhere far away from the typo."""
    r = client.get("/api/v1/bogus", headers=auth)
    assert r.status_code == 404
    assert r.json()["detail"].startswith("no such endpoint")


def test_an_unknown_api_path_still_demands_a_token(client: TestClient) -> None:
    """404 only for a caller who got past auth.

    Answering an unauthenticated caller with 404-for-unknown and 401-for-real
    would hand any page that reaches loopback a way to enumerate the routes --
    which is the surface the disabled OpenAPI docs already deny.
    """
    assert client.get("/api/v1/bogus").status_code == 401


def test_an_unknown_api_path_is_a_404_for_writes_too(
    client: TestClient, auth: dict[str, str]
) -> None:
    """The old catch-all was GET-only, so a POST typo came back 405."""
    r = client.post("/api/v1/bogus", headers=auth, json={})
    assert r.status_code == 404


def test_a_wrong_api_version_does_not_get_the_dashboard(client: TestClient) -> None:
    r = client.get("/api/v2/health")
    assert r.status_code == 404
    assert "<!doctype html>" not in r.text.lower()


@pytest.mark.parametrize(
    "path",
    [
        "/../config.json",
        "/../../config.json",
        "/%2e%2e%2f%2e%2e%2fconfig.json",
        "/....//config.json",
        "/..%2Fconfig.json",
        "/../identity.key",
        "/../../../../../../etc/passwd",
    ],
)
def test_traversal_never_escapes_the_bundle(client: TestClient, path: str) -> None:
    r = client.get(path)
    # Falling back to index.html is the correct outcome; leaking is not.
    assert "dashboard_token" not in r.text
    assert "root:" not in r.text
    if r.status_code == 200:
        assert "<!doctype html>" in r.text.lower()
