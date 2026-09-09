"""Starting Haze when the donor logs in, and stopping it just as easily.

The machine whose GPU makes this project worth anything is usually a Windows
gaming PC, and the person in front of it does not use a terminal.  ``haze up``
runs in the foreground, so without something here a borrowed GPU stops being
borrowed the moment its owner reboots -- and getting it back means opening
PowerShell, which is exactly the thing they will not do.

What this writes is a plain ``.cmd`` file in the Startup folder.  Not a
scheduled task, not a service, not a registry key: a file the owner can open in
Notepad, read, and delete.  That matters more here than polish does.  A tool
whose whole premise is *running someone else's code on your machine* has to be
legible to the person lending the machine, and an entry buried in Task
Scheduler's MMC tree is not legible.  It also means there are three independent
off switches -- ``haze autostart disable``, deleting the file, and Task
Manager's "Startup apps" tab, which lists Startup-folder entries -- against one
on switch.

The layout mirrors :mod:`haze.jobs.winjob`: everything that decides *what* to
write is a pure function taking its inputs as arguments, so it runs and is
tested on any OS, and only a thin shell at the bottom touches the disk.  That
is what lets a Mac verify the generated batch file is correct without a Windows
machine in the loop.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from haze import log

_log = log.get("autostart")

STARTUP_FILENAME = "Haze.cmd"
"""Named so it is recognisable in Task Manager's Startup apps tab, which shows
the file name and nothing else."""

CONSOLE_FILENAME = "Haze Console.cmd"

MARKER = "Created by `haze autostart enable`"
"""Written into both files and checked before either is removed.  ``disable``
deletes only what ``enable`` wrote; a file someone else put at the same path is
left alone and reported."""

# The Start Menu lives under %APPDATA%, which is per-user and needs no
# administrator.  The strictly correct lookup is SHGetKnownFolderPath with
# FOLDERID_Startup, since the location is relocatable through the registry --
# but that is a ctypes surface to maintain for a case approximately nobody
# hits, and getting it wrong here means a shortcut that does not appear, not a
# security hole.  `enable` checks the directory exists and says so if it does
# not, which turns the rare wrong answer into a message instead of a silence.
_START_MENU_PARTS = ("Microsoft", "Windows", "Start Menu", "Programs")


class AutostartError(Exception):
    """Something that stopped autostart being configured, with the remedy in
    the message.  The CLI layer turns this into one red line."""


@dataclass(frozen=True)
class Entry:
    """One file to write, and what belongs in it."""

    path: Path
    body: str


# --- pure: where the files go ------------------------------------------------

def start_menu_dir(env: Mapping[str, str]) -> Path:
    """The per-user Start Menu Programs folder."""
    appdata = env.get("APPDATA", "")
    if not appdata:
        raise AutostartError(
            "  APPDATA is not set, so the Start Menu folder cannot be located.\n"
            "  This command is for Windows; on macOS and Linux, start `haze up`\n"
            "  from launchd or `systemd --user` instead."
        )
    return Path(appdata).joinpath(*_START_MENU_PARTS)


def startup_dir(env: Mapping[str, str]) -> Path:
    """The folder Windows runs at login.  Reachable as `shell:startup`."""
    return start_menu_dir(env) / "Startup"


# --- pure: what goes in them -------------------------------------------------

def validate_exe_path(exe: Path) -> None:
    """Refuse a path that would produce a batch file meaning something else.

    Only two characters actually matter inside a double-quoted argument in a
    ``.cmd`` file.  ``%`` still expands there, so a user profile at
    ``C:\\Users\\100%``  would silently resolve to something else or to nothing.
    ``"`` would close the quoting -- it cannot occur in a real Windows path,
    which is precisely why an assertion is the right response if it ever does.

    ``&``, ``^``, ``|`` and ``!`` are *not* special inside the quotes and are
    legal in Windows file names, so rejecting them would break real users
    (``C:\\Users\\Ben & Kate``) to guard against nothing.
    """
    raw = str(exe)
    bad = {ch for ch in ('%', '"', "\r", "\n") if ch in raw}
    if bad:
        listed = " ".join(sorted(bad))
        raise AutostartError(
            f"  The path to haze contains {listed!r}, which a Windows batch file\n"
            f"  cannot carry safely:\n"
            f"      {raw}\n"
            f"  Reinstall haze somewhere without it, or start Haze by hand with\n"
            f"  `haze up`."
        )


def startup_body(exe: Path) -> str:
    """The login entry: start the agent minimised, without opening a browser.

    ``start`` reads a lone quoted argument as the *window title*, so the
    explicit "Haze" title is load-bearing -- drop it and the quoted path to the
    executable is consumed as the title and nothing launches.  It also gives the
    taskbar button a name the owner recognises.

    ``/min`` rather than a hidden window is deliberate.  Something is running on
    this machine on someone else's behalf; it should be visible in the taskbar,
    and closing that window should stop it.
    """
    return (
        "@echo off\r\n"
        f"REM {MARKER}.\r\n"
        "REM\r\n"
        "REM Haze starts with Windows and lends this machine to computers you\r\n"
        "REM have paired with.  To stop that, either delete this file or run:\r\n"
        "REM\r\n"
        "REM     haze autostart disable\r\n"
        "REM\r\n"
        "REM Closing the minimised Haze window stops the agent until next login.\r\n"
        f'start /min "Haze" "{exe}" up --no-open\r\n'
    )


def console_body(exe: Path) -> str:
    """The Start Menu entry: open the dashboard for whichever agent is running.

    Deliberately `haze open` and not a saved URL.  The dashboard port is scanned
    at startup and the token is per-machine, so the address is only knowable at
    run time -- `haze open` reads it out of ~/.haze/agent.json, which is exactly
    the job it already does.
    """
    return (
        "@echo off\r\n"
        f"REM {MARKER}.\r\n"
        "REM Opens the Haze dashboard for the agent running on this machine.\r\n"
        "REM Remove this entry, and stop Haze starting with Windows, with:\r\n"
        "REM\r\n"
        "REM     haze autostart disable\r\n"
        f'"{exe}" open\r\n'
    )


def entries(env: Mapping[str, str], exe: Path) -> list[Entry]:
    """Both files, in the order they should be reported."""
    validate_exe_path(exe)
    return [
        Entry(startup_dir(env) / STARTUP_FILENAME, startup_body(exe)),
        Entry(start_menu_dir(env) / CONSOLE_FILENAME, console_body(exe)),
    ]


# --- impure: finding haze, and touching the disk ------------------------------

def haze_executable() -> Path:
    """The `haze` command to point the shortcuts at.

    PATH first, because that is the one the owner will also type.  Failing that,
    the console script sits beside the interpreter running us -- uv installs
    tools into a venv whose Scripts directory holds both.
    """
    found = shutil.which("haze")
    if found:
        return Path(found)

    sibling = Path(sys.executable).with_name("haze.exe")
    if sibling.exists():
        return sibling

    raise AutostartError(
        "  Could not find the `haze` command to point the shortcut at.\n"
        "  Looked on PATH, and next to the running interpreter:\n"
        f"      {sibling}\n"
        "  Reinstall with `uv tool install haze-agent` and try again."
    )


def _write(entry: Entry) -> None:
    if not entry.path.parent.is_dir():
        raise AutostartError(
            f"  This folder does not exist, so the shortcut cannot be written:\n"
            f"      {entry.path.parent}\n"
            f"  Press Win+R, type `shell:startup`, and tell us what path opens."
        )
    # UTF-8 without a BOM. Every byte of an ASCII path is identical under the
    # code pages cmd.exe uses, which covers any ordinary Windows profile; a
    # profile directory containing characters outside the console code page is
    # the one case this does not serve, and `haze autostart status` re-reads the
    # file so a mismatch shows up rather than hiding.
    entry.path.write_text(entry.body, encoding="utf-8", newline="")
    _log.debug("wrote %s", entry.path)


def enable(env: Mapping[str, str], exe: Path) -> list[Path]:
    """Write both shortcuts.  Returns the paths written, in report order."""
    written = []
    for entry in entries(env, exe):
        _write(entry)
        written.append(entry.path)
    return written


def _paths(env: Mapping[str, str]) -> list[Path]:
    """Both shortcut paths, without needing to know where haze is installed.

    `disable` and `status` have to work when the executable has already been
    uninstalled, which is exactly when someone wants to clean up after it.
    """
    return [startup_dir(env) / STARTUP_FILENAME,
            start_menu_dir(env) / CONSOLE_FILENAME]


def disable(env: Mapping[str, str]) -> tuple[list[Path], list[Path]]:
    """Remove both shortcuts.

    Returns (removed, foreign).  A file we did not write is never deleted -- it
    is returned instead, so the CLI can name it rather than quietly taking
    someone else's shortcut along with ours.
    """
    removed: list[Path] = []
    foreign: list[Path] = []
    for path in _paths(env):
        if not path.exists():
            continue
        if MARKER not in path.read_text(encoding="utf-8", errors="replace"):
            foreign.append(path)
            continue
        path.unlink()
        removed.append(path)
    return removed, foreign


def status(env: Mapping[str, str]) -> list[tuple[Path, bool]]:
    """Each shortcut and whether it is currently in place."""
    return [(path, path.exists()) for path in _paths(env)]
