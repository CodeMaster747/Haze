"""Caching what peers say they can run.

Placement now happens on the submit path, where `probe_peers` opening a fresh
TLS connection to every paired machine is no longer a rare, user-initiated
cost -- it is latency on every job. These tests pin the two properties that
make caching it safe: a success is reused, and a *failure* is not reused for
long, because an unreachable peer reports no runtimes and the scheduler turns
that into "cannot run this job".
"""

from __future__ import annotations

from typing import Any

import pytest

from haze.config import Config
from haze.db import peers as peer_db
from haze.db import session as db_session
from haze.scheduler import cluster
from haze.transport import client as node_client

NODE_A = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
NODE_B = "ZZZZZZZ-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"

CAPS: dict[str, Any] = {"runtimes": ["hashbench"], "caps": {"max_cores": 8}}


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """A real database, and an empty cache.

    Both are module globals, so both have to be reset between tests or the
    second one silently inherits the first one's state.
    """
    monkeypatch.setenv("HAZE_HOME", str(tmp_path / "haze"))
    await db_session.init()
    cluster.invalidate_capabilities()
    yield
    cluster.invalidate_capabilities()
    await db_session.close()


async def _paired(node_id: str = NODE_A, name: str = "builder"):
    return await peer_db.upsert(
        node_id=node_id,
        public_key=node_id.encode()[:32].ljust(32, b"\x00"),
        cert_der=b"not-a-real-certificate",
        display_name=name,
        host="10.0.0.4",
        port=8443,
    )


def _cfg() -> Config:
    return Config(
        node_name="test-node", api_port=7433, node_port=8443,
        beacon_port=47654, dashboard_token="test-token-not-a-real-secret",
    )


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch):
    """Stand in for the network, counting who was asked and how often."""
    asked: list[str] = []

    def install(reachable: set[str]) -> list[str]:
        async def fake(node_id: str, *_a: Any, **_k: Any) -> dict[str, Any]:
            asked.append(node_id)
            if node_id not in reachable:
                raise node_client.ConnectError("asleep")
            return CAPS
        monkeypatch.setattr(node_client, "peer_capabilities", fake)
        return asked

    return install


async def test_no_peers_means_no_probing_at_all(db, answers) -> None:
    asked = answers(set())
    assert await cluster.cached_capabilities(None, _cfg()) == {}
    assert asked == []


async def test_a_peers_answer_is_reused_rather_than_asked_for_twice(db, answers) -> None:
    await _paired()
    asked = answers({NODE_A})

    first = await cluster.cached_capabilities(None, _cfg())
    second = await cluster.cached_capabilities(None, _cfg())

    assert first == second == {NODE_A: CAPS}
    assert asked == [NODE_A], "the second placement should have cost nothing"


async def test_silence_expires_much_sooner_than_an_answer(db, answers) -> None:
    """The asymmetry this cache is built around.

    A stale success is harmless -- installed software does not vanish. A stale
    failure is not: a peer that did not answer reports no runtimes, so caching
    silence for as long as an answer would lock a machine that just woke up out
    of placement entirely.
    """
    await _paired(NODE_A, "reachable")
    await _paired(NODE_B, "asleep")
    answers({NODE_A})

    await cluster.cached_capabilities(None, _cfg())

    reachable_ttl = cluster._cache[NODE_A].expires_at
    asleep_ttl = cluster._cache[NODE_B].expires_at
    assert asleep_ttl < reachable_ttl
    assert reachable_ttl - asleep_ttl == pytest.approx(
        cluster.CAPABILITIES_TTL_S - cluster.CAPABILITIES_MISS_TTL_S
    )


async def test_a_peer_that_wakes_up_is_asked_again(db, answers) -> None:
    await _paired()
    asked = answers(set())

    assert await cluster.cached_capabilities(None, _cfg()) == {}
    # Rather than faking the clock: expiry is the only thing under test, and
    # patching time.monotonic out from under a running event loop is a much
    # larger blast radius than setting one number.
    cluster._cache[NODE_A].expires_at = 0.0

    answers({NODE_A})
    assert await cluster.cached_capabilities(None, _cfg()) == {NODE_A: CAPS}
    assert asked == [NODE_A, NODE_A]


async def test_unpairing_a_node_drops_it_from_the_cache(db, answers) -> None:
    """No invalidation callback exists, and none is needed: the cache is
    reconciled against the live peer list on every call."""
    await _paired()
    answers({NODE_A})
    await cluster.cached_capabilities(None, _cfg())
    assert NODE_A in cluster._cache

    await peer_db.remove(NODE_A)
    assert await cluster.cached_capabilities(None, _cfg()) == {}
    assert cluster._cache == {}


async def test_a_newly_paired_node_is_asked_immediately(db, answers) -> None:
    await _paired(NODE_A, "first")
    asked = answers({NODE_A, NODE_B})
    await cluster.cached_capabilities(None, _cfg())
    assert asked == [NODE_A]

    await _paired(NODE_B, "second")
    result = await cluster.cached_capabilities(None, _cfg())

    assert set(result) == {NODE_A, NODE_B}
    assert asked == [NODE_A, NODE_B], "only the new peer should have been asked"
