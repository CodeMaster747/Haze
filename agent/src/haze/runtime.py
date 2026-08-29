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
from haze.db import peers as peer_db
from haze.db import session as db
from haze.discovery.registry import DiscoveryRegistry
from haze.identity import certs
from haze.identity.keys import Identity, load_or_create
from haze.pairing.manager import PairingManager
from haze.probe.base import ResourceProbe
from haze.probe.host import HostProbe
from haze.probe.synthetic import SyntheticProbe
from haze.probe.synthetic import load as load_profile
from haze.transport.server import NodeServer

_log = log.get("runtime")


@dataclass
class Agent:
    cfg: Config
    identity: Identity
    pairing: PairingManager
    node_server: NodeServer
    probe: ResourceProbe
    discovery: DiscoveryRegistry | None

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    @property
    def simulated(self) -> bool:
        return self.probe.simulated


async def start(
    cfg: Config,
    *,
    serve_peers: bool = True,
    discover: bool = True,
    profile: str | None = None,
) -> Agent:
    """Bring up identity, storage, telemetry, discovery and the node listener.

    ``profile`` selects a synthetic hardware profile instead of reading the real
    machine. That is what `haze devnet` uses to put four heterogeneous nodes on
    one laptop -- and every node started this way reports ``simulated: true``
    all the way to the dashboard badge.
    """
    await db.init()

    identity = load_or_create()
    # Generated from the identity key, so this is a no-op after the first run
    # unless the certificate expired or the key changed underneath it.
    certs.load_or_create(identity)

    pairing = PairingManager(identity.public_key)
    node_server = NodeServer(cfg, identity, pairing)

    probe: ResourceProbe
    if profile is not None:
        probe = SyntheticProbe(load_profile(profile))
        _log.info("node %s (%s) -- SIMULATED, profile %r", cfg.node_name, identity.short_id, profile)
    else:
        probe = HostProbe(cfg.node_name)
        _log.info("node %s (%s)", cfg.node_name, identity.short_id)

    if serve_peers:
        await node_server.start()

    discovery: DiscoveryRegistry | None = None
    if discover:
        discovery = DiscoveryRegistry(
            identity.node_id, cfg.node_name, cfg.node_port, cfg.beacon_port
        )
        await discovery.start()
        # Seed the paired set so the UI can distinguish "a machine I trust that
        # just came online" from "an unknown machine on this network".
        discovery.set_paired({p.node_id for p in await peer_db.all_peers()})

    return Agent(
        cfg=cfg,
        identity=identity,
        pairing=pairing,
        node_server=node_server,
        probe=probe,
        discovery=discovery,
    )


async def stop(agent: Agent) -> None:
    if agent.discovery is not None:
        await agent.discovery.stop()
    await agent.node_server.stop()
    await db.close()
