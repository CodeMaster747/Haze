"""What Haze tells a user about an address it could not reach.

Access-point client isolation is a real and common cause of a timeout on a
LAN, and a useless thing to say about a machine reached over an overlay
network or the open internet -- it sends the user to their router settings for
a problem that is not there. Every assertion here is about the agent not
volunteering a diagnosis it has no evidence for.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

from haze import cli_pairing
from haze.transport.client import _timeout_hint

_Addr = namedtuple("_Addr", "address")


# --- what a timeout is blamed on --------------------------------------------

@pytest.mark.parametrize("host", ["192.168.1.42", "10.0.0.5", "172.16.4.1"])
def test_a_lan_timeout_still_names_client_isolation(host: str) -> None:
    """The original diagnosis was right for the network it was written for."""
    assert "access point" in _timeout_hint(host)


@pytest.mark.parametrize("host", ["100.64.0.5", "100.101.102.103", "fd7a:115c:a1e0::1"])
def test_an_overlay_timeout_is_not_blamed_on_the_access_point(host: str) -> None:
    """THE regression. Two machines on Tailscale are not on one access point,
    and may not share a network at all -- the router is the wrong place to
    look, and Tailscale being down is the right one."""
    hint = _timeout_hint(host)
    assert "access point" not in hint
    assert "tailscale status" in hint.lower()


@pytest.mark.parametrize("host", ["203.0.113.9", "8.8.8.8"])
def test_a_public_timeout_points_at_the_firewall(host: str) -> None:
    hint = _timeout_hint(host)
    assert "access point" not in hint
    assert "firewall" in hint or "port forward" in hint


def test_a_hostname_gets_no_diagnosis_it_cannot_support() -> None:
    """A name says nothing about which network the machine is on, so the hint
    must not guess. `ip_address` raises on a name -- that path has to be
    handled, not left to escape as a ValueError."""
    hint = _timeout_hint("builder.example.com")
    assert "access point" not in hint
    assert "tailscale" not in hint.lower()


def test_the_ranges_do_not_lean_on_is_private() -> None:
    """`is_private` answers "not globally reachable", which is a broader
    question than "is this a LAN address" and not a stable one: it is True for
    the documentation ranges, and Python 3.12 reports False for the shared
    range Tailscale allocates from. Classifying on it would make this hint
    depend on the interpreter."""
    import ipaddress

    assert ipaddress.ip_address("203.0.113.9").is_private is True   # documentation range
    assert ipaddress.ip_address("100.64.0.5").is_private is False   # Tailscale's range

    assert "access point" not in _timeout_hint("203.0.113.9")
    assert "access point" not in _timeout_hint("100.64.0.5")


# --- which address `haze pair --serve` offers -------------------------------

def test_an_overlay_address_is_offered_when_one_exists(monkeypatch) -> None:
    """The default route names the LAN interface. On a machine whose peers are
    reached over Tailscale that is the wrong address to print, and the user
    has no way to know it."""
    monkeypatch.setattr(cli_pairing, "_default_route_address", lambda: "192.168.1.42")
    monkeypatch.setattr(cli_pairing, "_overlay_address", lambda: "100.64.0.5")

    offered = cli_pairing._address_hints()
    assert [address for address, _ in offered] == ["192.168.1.42", "100.64.0.5"]
    assert offered[1][1], "the overlay address needs a label saying when to use it"


def test_only_the_lan_address_is_offered_without_an_overlay(monkeypatch) -> None:
    monkeypatch.setattr(cli_pairing, "_default_route_address", lambda: "192.168.1.42")
    monkeypatch.setattr(cli_pairing, "_overlay_address", lambda: "")

    assert [a for a, _ in cli_pairing._address_hints()] == ["192.168.1.42"]


def test_an_overlay_only_machine_still_gets_an_address(monkeypatch) -> None:
    """A machine with no default route used to print a placeholder even when
    it had a perfectly good overlay address."""
    monkeypatch.setattr(cli_pairing, "_default_route_address", lambda: "")
    monkeypatch.setattr(cli_pairing, "_overlay_address", lambda: "100.64.0.5")

    assert [a for a, _ in cli_pairing._address_hints()] == ["100.64.0.5"]


def test_an_address_is_not_offered_twice(monkeypatch) -> None:
    """On an exit node the default route *is* the overlay interface."""
    monkeypatch.setattr(cli_pairing, "_default_route_address", lambda: "100.64.0.5")
    monkeypatch.setattr(cli_pairing, "_overlay_address", lambda: "100.64.0.5")

    assert [a for a, _ in cli_pairing._address_hints()] == ["100.64.0.5"]


def test_something_is_always_offered(monkeypatch) -> None:
    """With no address at all the instruction still has to read as an
    instruction, not as an empty line."""
    monkeypatch.setattr(cli_pairing, "_default_route_address", lambda: "")
    monkeypatch.setattr(cli_pairing, "_overlay_address", lambda: "")

    assert len(cli_pairing._address_hints()) == 1


def test_the_overlay_address_is_found_among_real_interfaces(monkeypatch) -> None:
    """psutil reports every interface; only the shared-range one is Tailscale's."""
    import psutil

    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {
        "lo0": [_Addr("127.0.0.1")],
        "en0": [_Addr("192.168.1.42"), _Addr("fe80::1%en0")],
        "utun3": [_Addr("100.64.0.5")],
    })
    assert cli_pairing._overlay_address() == "100.64.0.5"


def test_no_overlay_address_is_invented(monkeypatch) -> None:
    import psutil

    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {
        "lo0": [_Addr("127.0.0.1")],
        "en0": [_Addr("192.168.1.42")],
    })
    assert cli_pairing._overlay_address() == ""
