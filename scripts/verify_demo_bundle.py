#!/usr/bin/env python3
"""Assert the deployed demo bundle cannot contact a local agent.

The demo is served from an HTTPS origin. If it shipped code that reached for
`http://127.0.0.1`, Safari would block it as mixed content and Chrome would
raise a Local Network Access prompt -- so a visitor's first impression of the
project would be a security warning about a request that was never going to
work anyway.

`__HAZE_DEMO__` is a compile-time constant, so the minifier removes that code.
This checks it actually did, because "should be eliminated" and "was
eliminated" are different claims and only one of them is worth putting in the
README.

Run after `make build-demo`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "web" / "dist" / "assets"

# Anything that would indicate the agent-facing code path survived.
FORBIDDEN = [
    ("127.0.0.1", "a loopback address"),
    ("HttpAgentSource", "the live agent data source"),
    ("haze.token", "the dashboard bearer token"),
    ("/api/v1", "the agent API prefix"),
    ("new WebSocket", "a WebSocket constructor"),
]

# If these are gone too, the wrong bundle was checked.
REQUIRED = [("Haze", "the app itself")]


def main() -> int:
    bundles = sorted(DIST.glob("*.js"))
    if not bundles:
        print(f"no bundle in {DIST} — run `make build-demo` first", file=sys.stderr)
        return 1

    text = "\n".join(b.read_text(errors="replace") for b in bundles)
    failures: list[str] = []

    for needle, description in FORBIDDEN:
        if needle in text:
            failures.append(f"  FOUND {needle!r} ({description}) — it should have been eliminated")

    for needle, description in REQUIRED:
        if needle not in text:
            failures.append(f"  MISSING {needle!r} ({description}) — is this the right bundle?")

    names = ", ".join(b.name for b in bundles)
    if failures:
        print(f"demo bundle ({names}) is not clean:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1

    size = sum(b.stat().st_size for b in bundles)
    print(f"  demo bundle clean ({names}, {size // 1024} KiB)")
    print("  contains no loopback address, no agent API, no WebSocket")
    return 0


if __name__ == "__main__":
    sys.exit(main())
