"""Node IDs and the SAS.

These are pure functions, and they are where the security model's arithmetic
lives, so they get tested directly rather than only through the integration
suite.
"""

from __future__ import annotations

import os

import pytest

from haze.identity import nodeid
from haze.pairing import sas

# --- node ids ---------------------------------------------------------------

def test_node_id_is_stable_for_a_key() -> None:
    key = bytes(range(32))
    assert nodeid.from_public_key(key) == nodeid.from_public_key(key)


def test_node_id_has_the_documented_shape() -> None:
    node_id = nodeid.from_public_key(os.urandom(32))
    groups = node_id.split("-")
    assert len(groups) == 8
    assert all(len(g) == 7 for g in groups)
    assert nodeid.is_valid(node_id)


def test_node_id_rejects_a_wrong_length_key() -> None:
    with pytest.raises(ValueError, match="32-byte"):
        nodeid.from_public_key(b"too short")


def test_luhn_catches_every_single_character_substitution() -> None:
    """The check characters exist because a human retypes these off another
    screen. A substitution that slipped through would mean silently comparing
    two different nodes."""
    node_id = nodeid.from_public_key(os.urandom(32))
    flat = node_id.replace("-", "")

    missed = 0
    for position in range(len(flat)):
        for replacement in nodeid.ALPHABET:
            if replacement == flat[position]:
                continue
            corrupted = flat[:position] + replacement + flat[position + 1 :]
            if nodeid.is_valid(corrupted):
                missed += 1
    assert missed == 0, f"{missed} single-character corruptions were not detected"


def test_luhn_catches_adjacent_transpositions_within_a_group() -> None:
    """Transpositions inside a group's data are caught almost always.

    "Almost" is the honest word. Luhn mod-N misses a small set of pairs
    inherently -- decimal Luhn famously misses 09/90 -- so this asserts the
    measured rate rather than a perfection the scheme does not have.
    """
    total = caught = 0
    for _ in range(40):
        flat = nodeid.from_public_key(os.urandom(32)).replace("-", "")
        for i in range(len(flat) - 1):
            if flat[i] == flat[i + 1]:
                continue  # swapping identical characters is not an error
            if i % (13 + 1) == 12:
                continue  # the data<->check boundary; see the test below
            total += 1
            swapped = flat[:i] + flat[i + 1] + flat[i] + flat[i + 2 :]
            caught += not nodeid.is_valid(swapped)

    rate = caught / total
    assert rate > 0.98, f"only {rate:.1%} of in-group transpositions detected"


def test_swapping_a_check_character_is_structurally_undetectable() -> None:
    """Documents a real limitation rather than hiding it.

    A group's check character is computed from its data characters, so
    exchanging the last data character with the check character changes both
    sides of the equation together and always verifies.

    This is inherited from Syncthing's scheme and is acceptable because the node
    ID is a typo guard, not a security boundary -- trust decisions compare the
    raw Ed25519 public key. If this ever stops being true, this test fails and
    forces the question to be asked again.
    """
    flat = nodeid.from_public_key(os.urandom(32)).replace("-", "")
    undetected = 0
    checked = 0
    for group in range(4):
        i = group * 14 + 12  # last data char of the group
        if flat[i] == flat[i + 1]:
            continue
        checked += 1
        swapped = flat[:i] + flat[i + 1] + flat[i] + flat[i + 2 :]
        undetected += nodeid.is_valid(swapped)
    assert undetected == checked, "boundary swaps are expected to go undetected"


def test_normalise_accepts_what_a_human_types() -> None:
    node_id = nodeid.from_public_key(os.urandom(32))
    flat = node_id.replace("-", "")
    for sloppy in (flat.lower(), f"  {node_id}  ", flat.replace("O", "0").replace("I", "1")):
        assert nodeid.normalise(sloppy) == node_id


def test_short_id_is_the_first_group() -> None:
    node_id = nodeid.from_public_key(os.urandom(32))
    assert nodeid.short(node_id) == node_id.split("-")[0]


# --- SAS --------------------------------------------------------------------

def test_sas_is_order_independent() -> None:
    """Both machines must derive the same digits without agreeing who is first."""
    a, b = os.urandom(32), os.urandom(32)
    assert sas.digits(a, b) == sas.digits(b, a)
    assert sas.words(a, b) == sas.words(b, a)


def test_sas_is_six_digits_and_four_words() -> None:
    a, b = os.urandom(32), os.urandom(32)
    value = sas.digits(a, b)
    assert len(value) == 6 and value.isdigit()
    assert len(sas.words(a, b)) == 4


def test_a_machine_in_the_middle_cannot_make_the_screens_agree() -> None:
    """The core security claim.

    An attacker terminating both legs shows its own key to each side, so each
    side derives the SAS over a different pair. Run many times because a single
    collision is possible in principle at 20 bits; a systematic failure is not.
    """
    collisions = 0
    trials = 400
    for _ in range(trials):
        alice, bob, mallory = os.urandom(32), os.urandom(32), os.urandom(32)
        if sas.digits(alice, mallory) == sas.digits(mallory, bob):
            collisions += 1
    # 6 digits is ~20 bits; expected collisions over 400 trials is ~0.0004.
    assert collisions == 0, f"{collisions}/{trials} MITM attempts produced matching codes"


def test_sas_refuses_to_pair_a_node_with_itself() -> None:
    key = os.urandom(32)
    with pytest.raises(ValueError, match="itself"):
        sas.digits(key, key)


def test_sas_rejects_malformed_keys() -> None:
    with pytest.raises(ValueError, match="32-byte"):
        sas.digits(b"short", os.urandom(32))
