"""The loopback FastAPI application.

Architecture note -- why the dashboard is served from here rather than from the
deployed Firebase site:

A public https origin can no longer reach a local agent.  Safari hard-blocks
https -> http://127.0.0.1 as mixed content with no user override (WebKit bug
171934, open since 2017).  Chrome 142 (Oct 2025) began prompting for Local
Network Access on any public-origin request to loopback/RFC1918/.local, and
Chrome 147 (Apr 2026) extended that gate to WebSockets, closing the one
remaining workaround.

Same-address-space requests are explicitly exempt.  So the agent serves the SPA
itself and the browser only ever talks to one origin: http://127.0.0.1:<port>.
That single decision removes CORS, mixed content, the LNA prompt and certificate
warnings from the project simultaneously.  It is also what Syncthing (8384),
Jellyfin (8096), Home Assistant (8123) and Ollama (11434) all do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

import haze
from haze import log, runtime
from haze.api import routes_jobs, routes_pairing, security, ws
from haze.config import Config

_log = log.get("api.app")

WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"

_PLACEHOLDER = """<!doctype html><meta charset=utf-8>
<title>Haze - dashboard not built</title>
<style>body{font:15px/1.6 ui-monospace,Menlo,monospace;background:#0b0b0d;color:#f4f4f5;
padding:3rem;max-width:44rem;margin:auto}code{background:#1a1a1f;padding:.15rem .4rem;
border-radius:4px}a{color:#7c5cff}</style>
<h1>Haze agent is running</h1>
<p>The API is live, but the dashboard bundle has not been built into this
install yet.</p>
<p>From the repo root:</p>
<pre><code>make build-web</code></pre>
<p>Then restart the agent. The API itself is already usable:
<code>GET /api/v1/node</code>.</p>
"""


class _SecurityHeaders(BaseHTTPMiddleware):
    """Headers that matter for a loopback server reachable from any web page.

    Note what is *absent*: there is no CORSMiddleware and no
    Access-Control-Allow-Origin header anywhere in this app.  That is
    deliberate.  The dashboard is same-origin, so it needs no CORS grant, and
    adding one would hand cross-origin read access to exactly the attacker this
    server has to keep out.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # The token can arrive as ?t=... on the first navigation; keep that URL
        # out of any shared cache.
        if request.url.path == "/" or request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(
    cfg: Config,
    api_port: int,
    *,
    serve_peers: bool = True,
    discover: bool = True,
    profile: str | None = None,
) -> FastAPI:
    """Build the loopback app.

    ``serve_peers=False`` skips binding the node-to-node listener, which is what
    the test suite wants: it exercises the API without claiming a LAN port that
    a real agent (or a parallel test) might already hold.
    """
    security.configure(cfg.dashboard_token, api_port)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        agent = await runtime.start(
            cfg, serve_peers=serve_peers, discover=discover, profile=profile
        )
        app.state.agent = agent

        hub = ws.TelemetryHub(agent.probe)
        await hub.start()
        app.state.hub = hub

        _log.info("dashboard  %s", f"http://127.0.0.1:{api_port}/")
        try:
            yield
        finally:
            await hub.stop()
            await runtime.stop(agent)

    app = FastAPI(
        title="Haze Node Agent",
        version=haze.__version__,
        lifespan=lifespan,
        # No interactive docs: they are an unauthenticated surface that
        # enumerates every route for any page that gets past the origin check.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(_SecurityHeaders)

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(security.require_api_auth)])

    @api.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "version": haze.__version__,
                             "protocol": haze.PROTOCOL_VERSION})

    @api.get("/node")
    async def node() -> JSONResponse:
        """This node's own identity and current state."""
        hub: ws.TelemetryHub = app.state.hub
        agent: runtime.Agent | None = getattr(app.state, "agent", None)
        return JSONResponse(
            {
                "name": cfg.node_name,
                "node_id": agent.node_id if agent else None,
                "short_id": agent.identity.short_id if agent else None,
                "simulated": agent.simulated if agent else False,
                "api_port": api_port,
                "node_port": cfg.node_port,
                "version": haze.__version__,
                "snapshot": hub.latest(),
            }
        )

    api.include_router(routes_pairing.router)
    api.include_router(routes_jobs.router)
    app.include_router(api)

    @app.websocket("/ws")
    async def telemetry(socket: WebSocket) -> None:
        auth = await security.authorise_websocket(socket)
        if not auth.allowed:
            return  # authorise_websocket already closed the socket
        await socket.accept(subprotocol=auth.subprotocol)
        hub: ws.TelemetryHub = app.state.hub
        agent: runtime.Agent | None = getattr(app.state, "agent", None)
        await hub.serve(socket, agent)

    # --- static SPA, mounted last so it never shadows /api or /ws ------------
    if (WEBUI_DIR / "index.html").is_file():
        assets = WEBUI_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            # Serve a real file if one exists (favicon, manifest), otherwise
            # hand back index.html so client-side routes deep-link correctly.
            candidate = (WEBUI_DIR / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(WEBUI_DIR):
                return FileResponse(candidate)
            return FileResponse(WEBUI_DIR / "index.html")
    else:
        _log.warning("dashboard bundle missing at %s -- run `make build-web`", WEBUI_DIR)

        @app.get("/{path:path}", include_in_schema=False)
        async def placeholder(path: str) -> HTMLResponse:
            return HTMLResponse(_PLACEHOLDER)

    return app


async def serve(cfg: Config, api_port: int, *, profile: str | None = None) -> None:
    """Run uvicorn bound to the 127.0.0.1 literal."""
    import uvicorn

    config = uvicorn.Config(
        create_app(cfg, api_port, profile=profile),
        # NEVER 0.0.0.0.  This server can execute subprocesses; exposing it to
        # the LAN would hand that to anyone on the same WiFi.  Node-to-node
        # traffic uses the mutually-authenticated TLS listener instead.
        host="127.0.0.1",
        port=api_port,
        log_config=None,
        access_log=False,
    )
    await uvicorn.Server(config).serve()


__all__ = ["WEBUI_DIR", "create_app", "serve"]
