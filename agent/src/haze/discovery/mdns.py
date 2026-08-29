"""mDNS / DNS-SD discovery via python-zeroconf.

Registers `_haze._tcp.local.` and browses for peers. The TXT record carries the
node ID, and **the node ID is what identifies a peer** -- never the address.
`haze devnet` runs four agents behind one IP, so keying on address would
collapse them into one node.

Two failure modes are handled explicitly rather than left to surface as "no
peers found":

* **Another mDNS stack owns UDP 5353.** On Linux, ``avahi-daemon`` with
  ``disallow-other-stacks=yes`` prevents any other process from binding it. The
  NAS is the most likely machine to hit this. We detect the bind failure, name
  it, and let broadcast discovery carry on.
* **macOS Local Network privacy.** Since Sequoia, an app must be granted
  local-network permission before multicast works, and the prompt is attached
  to the *responsible* process. A tool launched from Terminal inherits
  Terminal's grant, but the same binary run from a LaunchAgent does not.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Callable

import haze
from haze import log
from haze.discovery.types import DiscoveredNode

_log = log.get("discovery.mdns")

SERVICE_TYPE = "_haze._tcp.local."

OnSeen = Callable[[DiscoveredNode], None]


class MdnsDiscovery:
    """Advertises this node and browses for others."""

    def __init__(self, node_id: str, name: str, node_port: int, on_seen: OnSeen) -> None:
        self._node_id = node_id
        self._name = name
        self._node_port = node_port
        self._on_seen = on_seen
        self._zc: object | None = None
        self._browser: object | None = None
        self._info: object | None = None

    async def start(self) -> bool:
        """Returns False if mDNS is unusable here; the caller falls back."""
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf
        except ImportError:  # pragma: no cover
            _log.warning("python-zeroconf not installed; mDNS discovery disabled")
            return False

        try:
            azc = AsyncZeroconf()
        except OSError as exc:
            self._explain_bind_failure(exc)
            return False

        # Instance name must be unique on the network. The short node ID makes
        # it so, and keeps several devnet agents on one host from colliding.
        short = self._node_id.split("-")[0]
        self._info = ServiceInfo(
            SERVICE_TYPE,
            f"{self._name}-{short}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(_primary_address())],
            port=self._node_port,
            properties={
                "v": str(haze.PROTOCOL_VERSION),
                "id": self._node_id,
                "name": self._name,
                "version": haze.__version__,
            },
            server=f"haze-{short.lower()}.local.",
        )

        try:
            await azc.async_register_service(self._info)
        except OSError as exc:
            self._explain_bind_failure(exc)
            with contextlib.suppress(Exception):
                await azc.async_close()
            return False

        self._zc = azc
        self._browser = AsyncServiceBrowser(
            azc.zeroconf, SERVICE_TYPE, handlers=[self._on_service_state_change]
        )
        _log.info("mDNS discovery advertising %s on port %d", SERVICE_TYPE, self._node_port)
        return True

    async def stop(self) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.async_cancel()  # type: ignore[attr-defined]
            self._browser = None
        if self._zc is not None:
            with contextlib.suppress(Exception):
                if self._info is not None:
                    await self._zc.async_unregister_service(self._info)  # type: ignore[attr-defined]
                await self._zc.async_close()  # type: ignore[attr-defined]
            self._zc = None

    def _on_service_state_change(self, zeroconf: object, service_type: str, name: str,
                                 state_change: object) -> None:
        # Fires on the zeroconf thread; hop back to the loop to resolve.
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self._resolve(service_type, name))

    async def _resolve(self, service_type: str, name: str) -> None:
        from zeroconf.asyncio import AsyncServiceInfo

        if self._zc is None:
            return
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(self._zc.zeroconf, 3000):  # type: ignore[attr-defined]
            return

        props = {
            k.decode(): v.decode()
            for k, v in (info.properties or {}).items()
            if isinstance(k, bytes) and isinstance(v, bytes)
        }
        node_id = props.get("id")
        if not node_id or node_id == self._node_id:
            return  # unrecognisable, or ourselves

        addresses = info.parsed_addresses()
        if not addresses:
            return

        self._on_seen(
            DiscoveredNode(
                node_id=node_id,
                name=props.get("name", "unnamed"),
                host=addresses[0],
                port=info.port or 0,
                sources={"mdns"},
                version=props.get("version", ""),
            )
        )

    def _explain_bind_failure(self, exc: OSError) -> None:
        _log.warning(
            "mDNS unavailable (%s). Another mDNS stack probably owns UDP 5353 -- on Linux "
            "that is avahi-daemon with `disallow-other-stacks=yes` in "
            "/etc/avahi/avahi-daemon.conf. Falling back to UDP broadcast; peers can also "
            "be added by address.",
            exc,
        )


def _primary_address() -> str:
    """The local address the routing table would use to leave this machine.

    Connecting a UDP socket sends nothing -- it only fixes a default
    destination, which is enough to learn the source address the kernel would
    pick. Beats guessing from the hostname, which resolves to 127.0.0.1 on
    plenty of Linux installs.
    """
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unroutable
        return str(s.getsockname()[0])
    return "127.0.0.1"
