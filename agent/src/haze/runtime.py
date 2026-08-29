"""The running agent: everything with a lifecycle, in one place.

Created once by `haze up` and shared by the dashboard API, the node listener
and the CLI. Keeping it here rather than in api/app.py means the FastAPI app
stays a transport detail -- the agent is not "a web app that also does
networking", it is a node that happens to expose a local web UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from haze import log
from haze.config import Config
from haze.db import session as db
from haze.identity import certs
from haze.identity.keys import Identity, load_or_create
from haze.pairing.manager import PairingManager
from haze.transport.server import NodeServer

_log = log.get("runtime")


@dataclass
class Agent:
    cfg: Config
    identity: Identity
    pairing: PairingManager
    node_server: NodeServer

    @property
    def node_id(self) -> str:
        return self.identity.node_id


async def start(cfg: Config, *, serve_peers: bool = True) -> Agent:
    """Bring up identity, storage and the node listener."""
    await db.init()

    identity = load_or_create()
    # Generated from the identity key, so this is a no-op after the first run
    # unless the certificate expired or the key changed underneath it.
    certs.load_or_create(identity)

    pairing = PairingManager(identity.public_key)
    node_server = NodeServer(cfg, identity, pairing)

    _log.info("node %s (%s)", cfg.node_name, identity.short_id)

    if serve_peers:
        await node_server.start()

    return Agent(cfg=cfg, identity=identity, pairing=pairing, node_server=node_server)


async def stop(agent: Agent) -> None:
    await agent.node_server.stop()
    await db.close()
