"""Short Authentication String — the six digits shown on both screens.

The security argument, which is the whole point of this module
--------------------------------------------------------------
The code is an **output** of both nodes' public keys, not an input. Nothing is
ever derived *from* the digits, so there is no secret to guess and nothing to
brute-force. This is the Signal safety-number / SSH fingerprint model.

A machine-in-the-middle has to terminate TLS on both legs, which means
substituting its own public key on at least one of them. Whatever it does, at
least one screen computes the SAS over a different key pair than the other, so
the two screens disagree and the user does not confirm.

What it costs: the user must be able to see both screens. That is fine for the
two-machines-on-a-desk case Haze targets, and it is why the docs describe
SPAKE2 (where the code is an input, typed on one side only) as the addition
needed for a headless NAS.

What it assumes: that the user actually compares. Six digits shown in a dialog
that is easy to click through is security theatre, so the UI presents them
large, on both ends, with an explicit "these must match" instruction.

Why sorted key material
-----------------------
Both nodes must derive the same value without agreeing on who is "first", so
the two public keys are sorted before hashing. Concatenating them in
connection order would give the initiator and responder different answers.
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Bump if the derivation ever changes: two nodes on different versions would
# otherwise silently show different digits and the user would blame themselves.
INFO = b"haze-sas-v1"

DIGITS = 6
_SAS_BYTES = 4

# PGP word list (even syllables). Shown alongside the digits because "adamant,
# bodyguard, chairlift, drifter" is far easier to compare across a room than
# "492817" -- and a mismatch in words is much harder to overlook.
_WORDS = (
    "aardvark", "absurd", "accrue", "acme", "adrift", "adult", "afflict", "ahead",
    "aimless", "Algol", "allow", "alone", "ammo", "ancient", "apple", "artist",
    "assume", "Athens", "atlas", "Aztec", "baboon", "backfield", "backward", "banjo",
    "beaming", "bedlamp", "beehive", "beeswax", "befriend", "Belfast", "berserk", "billiard",
    "bison", "blackjack", "blockade", "blowtorch", "bluebird", "bombast", "bookshelf", "brackish",
    "breadline", "breakup", "brickyard", "briefcase", "Burbank", "button", "buzzard", "cement",
    "chairlift", "chatter", "checkup", "chisel", "choking", "chopper", "Christmas", "clamshell",
    "classic", "classroom", "cleanup", "clockwork", "cobra", "commence", "concert", "cowbell",
    "crackdown", "cranky", "crowfoot", "crucial", "crumpled", "crusade", "cubic", "dashboard",
    "deadbolt", "deckhand", "dogsled", "dragnet", "drainage", "dreadful", "drifter", "dropper",
    "drumbeat", "drunken", "Dupont", "dwelling", "eating", "edict", "egghead", "eightball",
    "endorse", "endow", "enlist", "erase", "escape", "exceed", "eyeglass", "eyetooth",
    "facial", "fallout", "flagpole", "flatfoot", "flytrap", "fracture", "framework", "freedom",
    "frighten", "gazelle", "Geiger", "glitter", "glucose", "goggles", "goldfish", "gremlin",
    "guidance", "hamlet", "highchair", "hockey", "indoors", "indulge", "inverse", "involve",
    "island", "jawbone", "keyboard", "kickoff", "kiwi", "klaxon", "locale", "lockup",
    "merit", "minnow", "miser", "Mohawk", "mural", "music", "necklace", "Neptune",
    "newborn", "nightbird", "Oakland", "obtuse", "offload", "optic", "orca", "payday",
    "peachy", "pheasant", "physique", "playhouse", "Pluto", "preclude", "prefer", "preshrunk",
    "printer", "prowler", "pupil", "puppy", "python", "quadrant", "quiver", "quota",
    "ragtime", "ratchet", "rebirth", "reform", "regain", "reindeer", "rematch", "repay",
    "retouch", "revenge", "reward", "rhythm", "ribcage", "ringbolt", "robust", "rocker",
    "ruffled", "sailboat", "sawdust", "scallion", "scenic", "scorecard", "Scotland", "seabird",
    "select", "sentence", "shadow", "shamrock", "showgirl", "skullcap", "skydive", "slingshot",
    "slowdown", "snapline", "snapshot", "snowcap", "snowslide", "solo", "southward", "soybean",
    "spaniel", "spearhead", "spellbind", "spheroid", "spigot", "spindle", "spyglass", "stagehand",
    "stagnate", "stairway", "standard", "stapler", "steamship", "sterling", "stockman", "stopwatch",
    "stormy", "sugar", "surmount", "suspense", "sweatband", "swelter", "tactics", "talon",
    "tapeworm", "tempest", "tiger", "tissue", "tonic", "topmost", "tracker", "transit",
    "trauma", "treadmill", "Trojan", "trouble", "tumor", "tunnel", "tycoon", "uncut",
    "unearth", "unwind", "uproot", "upset", "upshot", "vapor", "village", "virus",
    "Vulcan", "waffle", "wallet", "watchword", "wayside", "willow", "woodlark", "Zulu",
)


def _material(key_a: bytes, key_b: bytes) -> bytes:
    for key in (key_a, key_b):
        if len(key) != 32:
            raise ValueError(f"expected a 32-byte Ed25519 public key, got {len(key)}")
    if key_a == key_b:
        # Both ends holding the same key means a node is pairing with itself --
        # a loopback or misconfiguration, never a legitimate pairing. Failing
        # here beats showing a confident, meaningless SAS.
        raise ValueError("cannot pair a node with itself: both public keys are identical")
    # Sorted so both ends agree without negotiating an order.
    return b"".join(sorted((key_a, key_b)))


def derive(key_a: bytes, key_b: bytes) -> bytes:
    """Raw SAS bytes for two raw Ed25519 public keys."""
    return HKDF(algorithm=hashes.SHA256(), length=_SAS_BYTES, salt=None, info=INFO).derive(
        _material(key_a, key_b)
    )


def digits(key_a: bytes, key_b: bytes) -> str:
    """The six digits shown to the user, e.g. ``"849271"``."""
    return f"{int.from_bytes(derive(key_a, key_b), 'big') % 10**DIGITS:0{DIGITS}d}"


def words(key_a: bytes, key_b: bytes) -> list[str]:
    """Four PGP words over the same material, one per SAS byte."""
    return [_WORDS[b] for b in derive(key_a, key_b)]


def matches(expected: str, supplied: str) -> bool:
    """Constant-time comparison of two SAS strings.

    The SAS is not a secret, so timing leakage is not really a threat here.
    Using compare_digest anyway costs nothing and means nobody has to re-derive
    that argument the next time this code is read.
    """
    return hmac.compare_digest(expected.strip(), supplied.strip())


def fingerprint_bytes(public_key: bytes) -> bytes:
    """SHA-256 of a raw public key. Used where a stable short handle is wanted
    but the node ID's grouping would be noise."""
    return hashlib.sha256(public_key).digest()
