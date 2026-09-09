"""Tiny client for the local agent's API, used by the CLI.

Deliberately stdlib-only. This talks to 127.0.0.1 over plain HTTP with a
bearer token; pulling in an HTTP library for that would add a dependency to the
*runtime* install for no benefit.

Every CLI command that mutates state goes through here rather than opening the
database directly. That keeps the running agent the single writer, so there is
no second process racing it on SQLite, and no way for the CLI to change the
peer table without the agent noticing.
"""

from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
from typing import Any

from haze import config


class AgentNotRunningError(Exception):
    """No local agent to talk to."""


class ApiError(Exception):
    """The agent replied with an error."""


def _endpoint() -> tuple[str, str, str]:
    """Return (base url, origin, token) for the running agent."""
    runtime = config.read_runtime()
    if runtime is None:
        raise AgentNotRunningError("no agent is running on this machine -- start one with `haze up`")

    port = int(runtime["api_port"])
    origin = f"http://127.0.0.1:{port}"
    return f"{origin}/api/v1", origin, config.load_or_create().dashboard_token


def request(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
    base, origin, token = _endpoint()
    data = json.dumps(body).encode() if body is not None else None

    req = urllib.request.Request(  # noqa: S310 -- fixed http://127.0.0.1 scheme
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            # Must match the agent's allowlist: the API rejects foreign origins
            # even with a valid token, and a CLI sending no Origin at all is
            # also fine. Sending our own keeps CLI and browser on one path.
            "Origin": origin,
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        # FastAPI wraps errors as {"detail": "..."}; anything else (a proxy
        # page, a truncated body) is shown verbatim rather than swallowed.
        with contextlib.suppress(json.JSONDecodeError, AttributeError):
            detail = json.loads(detail).get("detail", detail)
        raise ApiError(f"{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AgentNotRunningError(
            f"could not reach the agent: {exc.reason}. It may have stopped -- try `haze status`."
        ) from exc


def get(path: str, timeout: float = 15.0) -> Any:
    return request("GET", path, timeout=timeout)


def post(path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
    return request("POST", path, body or {}, timeout=timeout)


def put(path: str, body: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
    return request("PUT", path, body or {}, timeout=timeout)


def delete(path: str, timeout: float = 15.0) -> Any:
    return request("DELETE", path, timeout=timeout)
