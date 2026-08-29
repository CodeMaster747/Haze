"""The discovery registry.

The property that matters most here is that nodes are keyed by identity, not
address. `haze devnet` runs four agents behind one IP, and a registry that
keyed on host would collapse them into a single node -- silently, and in a way
that would look like a discovery bug rather than a design mistake.
"""

from __future__ import annotations

import time

from haze.discovery.registry import DiscoveryRegistry
from haze.discovery.types import STALE_AFTER_S, DiscoveredNode


def _registry() -> DiscoveryRegistry:
    return DiscoveryRegistry(node_id="SELF-ID", name="self", node_port=8443, beacon_port=47999)


def _seen(node_id: str, host: str = "192.168.1.10", port: int = 8443, **kw: object) -> DiscoveredNode:
    return DiscoveredNode(node_id=node_id, name=kw.pop("name", node_id), host=host, port=port, **kw)  # type: ignore[arg-type]


def test_nodes_sharing_one_address_stay_distinct() -> None:
    """THE devnet case. Four agents on one host advertise the same IP."""
    registry = _registry()
    for i, node_id in enumerate(["NODE-A", "NODE-B", "NODE-C", "NODE-D"]):
        registry._record(_seen(node_id, host="127.0.0.1", port=8801 + i))

    assert len(registry.nodes()) == 4
    assert {n.node_id for n in registry.nodes()} == {"NODE-A", "NODE-B", "NODE-C", "NODE-D"}


def test_a_node_is_never_confused_with_itself() -> None:
    registry = _registry()
    registry._record(_seen("SELF-ID"))
    assert registry.nodes() == []


def test_sources_accumulate_rather_than_replace() -> None:
    """Seen by broadcast but not mDNS is diagnostic -- it means multicast is
    being filtered on this network. Overwriting would destroy that signal."""
    registry = _registry()
    registry._record(_seen("NODE-A", sources={"mdns"}))
    registry._record(_seen("NODE-A", sources={"broadcast"}))

    node = registry.nodes()[0]
    assert node.sources == {"mdns", "broadcast"}


def test_a_node_that_changes_address_keeps_its_identity() -> None:
    """DHCP renewals and interface changes are non-events, not new nodes."""
    registry = _registry()
    registry._record(_seen("NODE-A", host="192.168.1.10"))
    registry._record(_seen("NODE-A", host="192.168.1.55"))

    assert len(registry.nodes()) == 1
    node = registry.nodes()[0]
    assert node.host == "192.168.1.55"
    # Reachability is invalidated: the old answer was about a different address.
    assert node.reachable is None


def test_stale_nodes_are_dropped_but_manual_ones_are_kept() -> None:
    """A manual entry is a user's explicit statement that a machine exists.
    Sweeping it away because it is quiet would delete their input."""
    registry = _registry()
    registry._record(_seen("NODE-A"))
    registry.add_manual("192.168.1.99", 8443)

    for node in registry.nodes():
        node.last_seen = time.monotonic() - (STALE_AFTER_S + 5)

    state = registry.state()
    remaining = {n["node_id"] for n in state["nodes"]}
    assert "NODE-A" not in remaining
    assert any(nid.startswith("manual:") for nid in remaining)


def test_paired_flag_tracks_the_peer_table() -> None:
    registry = _registry()
    registry._record(_seen("NODE-A"))
    registry._record(_seen("NODE-B"))

    registry.set_paired({"NODE-A"})
    by_id = {n.node_id: n for n in registry.nodes()}
    assert by_id["NODE-A"].paired is True
    assert by_id["NODE-B"].paired is False


def test_state_reports_which_mechanisms_are_running() -> None:
    """The dashboard shows these so a user can tell "nothing on the network"
    from "discovery could not start on this machine"."""
    state = _registry().state()
    assert state["mdns"] is False      # not started in this test
    assert state["broadcast"] is False
    assert state["nodes"] == []


def test_manual_entries_are_addressable_before_identity_is_known() -> None:
    """Adding by address gives us a host but no node ID -- and identity is the
    key. The placeholder is replaced once a handshake proves who is there."""
    registry = _registry()
    registry.add_manual("10.0.0.5", 8443)
    node = registry.nodes()[0]
    assert node.host == "10.0.0.5"
    assert "manual" in node.sources
    assert node.node_id.startswith("manual:")
