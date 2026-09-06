"""Haze -- pool your own machines into a private compute network."""

__version__ = "0.1.1"

# Bumped independently of __version__.  Two agents refuse to talk if their
# PROTOCOL_VERSION differs, so an old node on the LAN fails loudly at the
# handshake instead of subtly misparsing a frame three messages later.
PROTOCOL_VERSION = 1
