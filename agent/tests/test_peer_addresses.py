"""Pinned peer addresses, and the dial fallback built on them.

A peer's recorded address is rewritten on every inbound session, which is the
right behaviour for an observation and the wrong behaviour for a preference: a
machine reachable both on the LAN and over an overlay network flip-flops
between the two depending on which path it last dialled in on. A pin is the
user's statement of where to reach a machine, and the property that matters is
that nothing but the user changes it.

These are the first tests in the suite to touch the database directly. Peer
rows have only ever existed here via real subprocess pairing, which is far too
heavy to say anything about address ordering.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from haze.config import Config
from haze.db import peers as peer_db
from haze.db import session as db_session
from haze.transport import client

NODE_A = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
NODE_B = "ZZZZZZZ-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """A real SQLite database in a temp directory.

    HAZE_HOME redirects the state dir, so the suite never touches the
    developer's own ~/.haze. The engine is a module global, so it has to be
    disposed between tests or the second one would silently reuse the first
    one's file.
    """
    monkeypatch.setenv("HAZE_HOME", str(tmp_path / "haze"))
    await db_session.init()
    yield
    await db_session.close()


async def _paired(node_id: str = NODE_A, name: str = "builder", host: str = "", port: int = 0):
    """A paired peer. Nothing in these paths parses the key or certificate."""
    return await peer_db.upsert(
        node_id=node_id,
        public_key=node_id.encode()[:32].ljust(32, b"\x00"),
        cert_der=b"not-a-real-certificate",
        display_name=name,
        host=host,
        port=port,
    )


def _cfg() -> Config:
    return Config(
        node_name="test-node", api_port=7433, node_port=8443,
        beacon_port=47654, dashboard_token="test-token-not-a-real-secret",
    )


# --- the pin is the user's, and stays that way ------------------------------

async def test_an_observed_address_does_not_overwrite_a_pin(db) -> None:
    """THE case this feature exists for.

    Both machines are also on one LAN, the peer dials in over it, and the
    address the user pinned must survive that. Before pinning existed the
    inbound session simply overwrote it.
    """
    await _paired(host="100.64.0.5", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    await peer_db.touch(NODE_A, host="192.168.1.42", port=8443)

    pins = await peer_db.pinned(NODE_A)
    assert [(p.host, p.port) for p in pins] == [("100.64.0.5", 8443)]
    # The observation is still recorded -- it is a true fact about where the
    # peer connected from, and the fallback when the pin stops working.
    peer = await peer_db.get(NODE_A)
    assert (peer.last_host, peer.last_port) == ("192.168.1.42", 8443)


async def test_a_peer_with_only_a_pin_is_dialable(db) -> None:
    """A machine that has never dialled in has no observed address. Before
    this, that peer was unreachable no matter what the user knew."""
    await _paired()
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    peer = await peer_db.get(NODE_A)
    addresses = await client.peer_addresses(peer)
    assert [(a.host, a.port, a.source) for a in addresses] == [("100.64.0.5", 8443, "pinned")]


async def test_the_pinned_address_is_tried_before_the_observed_one(db) -> None:
    """Order is the whole point: the pin is the user's stated intent."""
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    peer = await peer_db.get(NODE_A)
    assert [a.source for a in await client.peer_addresses(peer)] == ["pinned", "last seen"]


async def test_an_address_that_is_both_pinned_and_observed_is_dialled_once(db) -> None:
    """Otherwise the common case -- pin the address it already connects from --
    would pay two timeouts to learn one fact."""
    await _paired(host="100.64.0.5", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    peer = await peer_db.get(NODE_A)
    assert len(await client.peer_addresses(peer)) == 1


async def test_re_pinning_replaces_rather_than_collides(db) -> None:
    """Pinning twice is what a user does when an address changes. A bare
    insert would raise UNIQUE constraint failed on the second one."""
    await _paired()
    assert await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    assert await peer_db.pin_address(NODE_A, "100.64.0.9", 9443)

    pins = await peer_db.pinned(NODE_A)
    assert [(p.host, p.port) for p in pins] == [("100.64.0.9", 9443)]


async def test_pinning_an_unpaired_node_is_refused(db) -> None:
    """A pin for a machine there is no trust decision about could never be
    used, and would outlive any future pairing."""
    assert await peer_db.pin_address(NODE_A, "100.64.0.5", 8443) is False


async def test_clearing_a_pin_leaves_the_peer_paired(db) -> None:
    """Clearing an address is not a revocation."""
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    assert await peer_db.clear_address(NODE_A) is True
    assert await peer_db.pinned(NODE_A) == []
    assert await peer_db.get(NODE_A) is not None


async def test_unpairing_forgets_the_pin_and_re_pairing_does_not_revive_it(db) -> None:
    """A node ID is derived from the public key, so the same machine re-pairing
    reuses it. Without an explicit delete the old pin would silently reattach
    -- and being tried first, would cost a full timeout on every dial.

    The FK cascade cannot be relied on for this: PRAGMA foreign_keys is
    per-connection and the engine pools connections.
    """
    await _paired()
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    assert await peer_db.remove(NODE_A) is True
    await _paired()  # the same machine, paired again

    assert await peer_db.pinned(NODE_A) == []


async def test_one_peers_pin_is_not_another_peers(db) -> None:
    await _paired(NODE_A, "builder")
    await _paired(NODE_B, "laptop")
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    assert await peer_db.pinned(NODE_B) == []
    assert (await peer_db.all_pins()).keys() == {NODE_A}


# --- the dial fallback ------------------------------------------------------

def _fake_connect(monkeypatch, reachable: set[str], hang: set[str] = frozenset()):
    """Replace the real dialler. Records every attempt in the returned list."""
    attempts: list[tuple[str, float]] = []

    @asynccontextmanager
    async def fake(host, port, identity, node_name, node_port,
                   expected_public_key=None, expected_cert=None,
                   timeout_s=client.CONNECT_TIMEOUT_S) -> AsyncIterator[object]:
        attempts.append((host, timeout_s))
        if host in hang:
            await asyncio.sleep(timeout_s)
            raise client.ConnectError(f"{host} did not respond", kind="timeout",
                                      brief=f"no response in {timeout_s:.0f}s")
        if host not in reachable:
            raise client.ConnectError(f"could not reach {host}", brief="refused")
        yield f"connection-to-{host}"

    monkeypatch.setattr(client, "connect", fake)
    return attempts


async def test_the_second_address_is_tried_when_the_first_fails(db, monkeypatch) -> None:
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    attempts = _fake_connect(monkeypatch, reachable={"192.168.1.42"})

    peer = await peer_db.get(NODE_A)
    async with client.connect_to_peer(peer, None, _cfg()) as conn:
        assert conn == "connection-to-192.168.1.42"

    assert [host for host, _ in attempts] == ["100.64.0.5", "192.168.1.42"]


async def test_a_reachable_pin_short_circuits_the_fallback(db, monkeypatch) -> None:
    """The observed address must not be dialled when the pin works -- that is
    the latency the pin is supposed to save."""
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    attempts = _fake_connect(monkeypatch, reachable={"100.64.0.5", "192.168.1.42"})

    peer = await peer_db.get(NODE_A)
    async with client.connect_to_peer(peer, None, _cfg()):
        pass

    assert [host for host, _ in attempts] == ["100.64.0.5"]


async def test_every_address_tried_is_named_when_all_of_them_fail(db, monkeypatch) -> None:
    """A user who pinned an address needs to see that it was tried and that
    the fallback was too -- otherwise they cannot tell which one to fix."""
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    _fake_connect(monkeypatch, reachable=set())

    peer = await peer_db.get(NODE_A)
    with pytest.raises(client.ConnectError) as caught:
        async with client.connect_to_peer(peer, None, _cfg()):
            pass

    message = str(caught.value)
    assert "100.64.0.5" in message and "192.168.1.42" in message
    assert "pinned" in message and "last seen" in message


async def test_a_single_failure_is_reported_exactly_as_before(db, monkeypatch) -> None:
    """The one-address case is still the common one, its wording is written
    for a user, and both the job route and the ping route pipe this string
    straight into a UI field sized for a sentence."""
    await _paired(host="192.168.1.42", port=8443)
    _fake_connect(monkeypatch, reachable=set())

    peer = await peer_db.get(NODE_A)
    with pytest.raises(client.ConnectError) as caught:
        async with client.connect_to_peer(peer, None, _cfg()):
            pass

    assert str(caught.value) == "could not reach 192.168.1.42"


async def test_a_certificate_mismatch_still_lets_the_next_address_through(db, monkeypatch) -> None:
    """Authentication binds to the public key, never to the address, so trying
    another address cannot admit an impostor -- it can only reach the real
    peer. Aborting instead would mean a pinned address later reassigned to some
    other machine takes the peer offline permanently.
    """
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    @asynccontextmanager
    async def fake(host, port, *args, **kwargs):
        if host == "100.64.0.5":
            raise client.ConnectError("wrong certificate", kind="identity")
        yield "connection"

    monkeypatch.setattr(client, "connect", fake)
    peer = await peer_db.get(NODE_A)
    async with client.connect_to_peer(peer, None, _cfg()) as conn:
        assert conn == "connection"


async def test_an_unreachable_machine_reports_the_certificate_problem_first(
    db, monkeypatch
) -> None:
    """A machine that answered with the wrong certificate is a more actionable
    fact than several that did not answer at all."""
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)

    @asynccontextmanager
    async def fake(host, port, *args, **kwargs):
        if host == "100.64.0.5":
            raise client.ConnectError("presented an unexpected certificate", kind="identity")
        raise client.ConnectError("no route to host", brief="no route")
        yield  # pragma: no cover

    monkeypatch.setattr(client, "connect", fake)
    peer = await peer_db.get(NODE_A)
    with pytest.raises(client.ConnectError) as caught:
        async with client.connect_to_peer(peer, None, _cfg()):
            pass

    assert "presented an unexpected certificate" in str(caught.value)
    assert caught.value.kind == "identity"


async def test_a_peer_with_no_address_at_all_says_how_to_give_it_one(db, monkeypatch) -> None:
    await _paired()
    _fake_connect(monkeypatch, reachable=set())

    peer = await peer_db.get(NODE_A)
    with pytest.raises(client.ConnectError, match="haze address"):
        async with client.connect_to_peer(peer, None, _cfg()):
            pass


# --- the time budget --------------------------------------------------------

async def test_a_black_holed_pin_cannot_starve_the_fallback(db, monkeypatch) -> None:
    """A silently-dropping firewall on the pinned address is the pathological
    case, and the likely one: the pin is user-typed. A plain
    min(CONNECT_TIMEOUT_S, remaining) would hand it most of the budget and
    leave the known-good address a sliver.
    """
    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    attempts = _fake_connect(monkeypatch, reachable={"192.168.1.42"}, hang={"100.64.0.5"})

    peer = await peer_db.get(NODE_A)
    async with client.connect_to_peer(peer, None, _cfg(), budget_s=4.0):
        pass

    budgets = dict(attempts)
    assert budgets["100.64.0.5"] == pytest.approx(2.0, abs=0.1), "half of a two-address budget"
    assert budgets["192.168.1.42"] >= client.MIN_ATTEMPT_S


async def test_capabilities_finish_inside_the_scheduler_probe_deadline(db, monkeypatch) -> None:
    """`probe_peers` wraps every capability call in wait_for(..., 4.0). A dial
    budget above that would be cancelled mid-attempt and the fallback address
    would never be tried -- the pin would work for ping and for jobs and do
    nothing at all for the scheduler, which is the hardest version of this to
    diagnose from the outside.
    """
    assert client.CAPABILITIES_BUDGET_S < 4.0

    await _paired(host="192.168.1.42", port=8443)
    await peer_db.pin_address(NODE_A, "100.64.0.5", 8443)
    _fake_connect(monkeypatch, reachable=set(), hang={"100.64.0.5", "192.168.1.42"})

    started = time.monotonic()
    with pytest.raises(client.ConnectError):
        await asyncio.wait_for(
            client.peer_capabilities(NODE_A, None, _cfg()), 4.0
        )
    assert time.monotonic() - started < 4.0, "the whole dial must fit inside the probe deadline"
