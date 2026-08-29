"""Authentication for the loopback dashboard API.

Threat being defended against
-----------------------------
The agent's API can start subprocesses and read shared paths.  It listens on
loopback, and *loopback is reachable from any web page the user visits*: in
Firefox today an arbitrary https page may open ``ws://127.0.0.1`` with no prompt
at all, and WebSocket upgrades carry no CORS preflight, so the browser sends the
request regardless of origin.  Without the two checks in this module, any site
the user opens in another tab could enumerate and drive their compute cluster.
That is the "Local Mess" bug class that motivated Chrome's Local Network Access
work, and it is why both checks below are tested rather than assumed.

Two independent gates, either of which alone is insufficient:

1. **Bearer token.**  Proves the caller read a 0600 file on this machine.
2. **Origin allowlist.**  Proves the caller is our own page (or a native client
   that sends no ``Origin`` at all), so a malicious page cannot ride along even
   if it somehow learned the token.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from starlette.websockets import WebSocket

from haze import log

_log = log.get("api.security")

# Set once at app construction; see app.create_app().
_TOKEN: str = ""
_ALLOWED_ORIGINS: frozenset[str] = frozenset()

WS_SUBPROTOCOL = "haze.v1"
# Not a credential: this is the prefix of a Sec-WebSocket-Protocol *name*,
# which the token is appended to by the client.
_WS_TOKEN_PREFIX = "haze.token."  # noqa: S105


@dataclass(frozen=True)
class WsAuth:
    """Outcome of a WebSocket upgrade check."""

    allowed: bool
    subprotocol: str | None


def configure(token: str, api_port: int) -> None:
    global _TOKEN, _ALLOWED_ORIGINS
    _TOKEN = token
    # Only our own loopback origin.  `localhost` is included because a user may
    # type it even though we advertise 127.0.0.1, but note that the *binding*
    # stays on the 127.0.0.1 literal -- on macOS the name `localhost` can
    # resolve to ::1 first, and binding a name you did not verify is how you
    # accidentally end up listening somewhere you did not intend.
    _ALLOWED_ORIGINS = frozenset(
        {
            f"http://127.0.0.1:{api_port}",
            f"http://localhost:{api_port}",
        }
    )


def _token_ok(candidate: str | None) -> bool:
    if not candidate or not _TOKEN:
        return False
    # compare_digest, not ==, so a wrong token cannot be recovered byte-by-byte
    # by timing the response.
    return hmac.compare_digest(candidate, _TOKEN)


def _origin_ok(origin: str | None) -> bool:
    # A missing Origin means a non-browser client (the `haze` CLI, curl, a
    # test).  Those still have to present the bearer token, which is the real
    # gate; browsers always send Origin, so this cannot be used to bypass.
    if origin is None:
        return True
    return origin in _ALLOWED_ORIGINS


def require_api_auth(request: Request) -> None:
    """FastAPI dependency guarding every ``/api`` route."""
    if not _origin_ok(request.headers.get("origin")):
        _log.warning("rejected /api call from foreign origin %r", request.headers.get("origin"))
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")

    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("t")
    if not _token_ok(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid token")


async def authorise_websocket(ws: WebSocket) -> WsAuth:
    """Validate a WebSocket upgrade.

    Returns :class:`WsAuth`.  Deliberately NOT ``str | None``: "rejected" and
    "accepted with no negotiated subprotocol" are both legitimate outcomes, and
    collapsing them into one sentinel silently drops every valid connection
    that did not offer a subprotocol.

    Browsers cannot set an ``Authorization`` header on a WebSocket, so the token
    arrives either in ``Sec-WebSocket-Protocol`` (preferred -- it keeps the
    token out of URLs, referrer headers and access logs) or as a ``?t=`` query
    parameter.
    """
    if not _origin_ok(ws.headers.get("origin")):
        _log.warning("rejected /ws upgrade from foreign origin %r", ws.headers.get("origin"))
        # Closing before accept() means the handshake never completes: the page
        # gets an error event and no data ever flows.
        await ws.close(code=1008, reason="origin not allowed")
        return WsAuth(False, None)

    offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    token = next((p[len(_WS_TOKEN_PREFIX):] for p in offered if p.startswith(_WS_TOKEN_PREFIX)), None)
    if token is None:
        token = ws.query_params.get("t")

    if not _token_ok(token):
        await ws.close(code=1008, reason="missing or invalid token")
        return WsAuth(False, None)

    # Echo back only the plain protocol name, never the token-bearing one --
    # the accepted subprotocol is visible to the page and to devtools.
    return WsAuth(True, WS_SUBPROTOCOL if WS_SUBPROTOCOL in offered else None)
