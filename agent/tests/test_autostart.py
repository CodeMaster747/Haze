"""What `haze autostart` writes, verified without a Windows machine.

The module under test is deliberately split so this file can exist: everything
that decides *what* goes into the Startup folder is a pure function taking the
environment and the executable path as arguments.  What is left untested here
is only whether Windows runs a `.cmd` dropped in that folder, which it has done
since Windows 95 and which the windows-2022 CI job exercises for real.

The batch file is the interesting artefact.  It is generated text that a shell
will later parse, and the two ways to get that wrong -- losing the executable
into `start`'s window-title argument, and letting `%` through into a quoted
path -- are both silent.  Nothing crashes; Haze just never starts, on a machine
belonging to someone who is doing you a favour and will not debug it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from haze import autostart


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A fake %APPDATA% with the Start Menu tree already laid out.

    Real Windows always has these folders; creating them is what makes this a
    test of the generated content rather than of `mkdir`.
    """
    appdata = tmp_path / "AppData" / "Roaming"
    (appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup").mkdir(parents=True)
    return {"APPDATA": str(appdata)}


EXE = Path(r"C:\Users\donor\.local\bin\haze.exe")


# --- where the files go ------------------------------------------------------

def test_the_startup_folder_is_the_one_shell_startup_opens(env: dict[str, str]) -> None:
    """`shell:startup` resolves to Programs\\Startup under %APPDATA%.

    If this drifts, `haze autostart enable` writes a file nothing ever reads and
    reports success -- the worst available outcome.
    """
    assert autostart.startup_dir(env).parts[-5:] == (
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )
    assert autostart.start_menu_dir(env) == autostart.startup_dir(env).parent


def test_a_missing_appdata_names_the_platform_rather_than_crashing() -> None:
    """The message has to be useful to someone who ran this on a Mac."""
    with pytest.raises(autostart.AutostartError, match="APPDATA"):
        autostart.startup_dir({})


# --- what goes in them -------------------------------------------------------

def test_the_startup_entry_gives_start_an_explicit_window_title() -> None:
    """`start "Haze" "C:\\...\\haze.exe"` -- the title is not decoration.

    cmd's `start` reads a lone quoted argument as the window title.  Without the
    explicit "Haze", the quoted path to the executable is swallowed as the title
    and `start` opens a bare shell instead of running Haze.  It fails silently
    and only at login, which is why it is asserted here.
    """
    body = autostart.startup_body(EXE)
    assert f'start /min "Haze" "{EXE}" up --no-open' in body


def test_the_startup_entry_does_not_open_a_browser_at_every_login() -> None:
    """`haze up` opens a tab by default; at login that is an ambush."""
    assert "--no-open" in autostart.startup_body(EXE)


def test_the_console_entry_asks_haze_where_the_dashboard_is() -> None:
    """Not a baked-in URL.

    The API port is scanned at startup and the token is per-machine, so the
    address is only knowable at run time.  `haze open` reads it out of the
    runtime file, which is the job it already does.
    """
    body = autostart.console_body(EXE)
    assert f'"{EXE}" open' in body
    assert "127.0.0.1" not in body


@pytest.mark.parametrize("body", [autostart.startup_body(EXE), autostart.console_body(EXE)])
def test_every_generated_file_says_how_to_remove_itself(body: str) -> None:
    """The off switch is discoverable from the artefact alone.

    Someone who finds `Haze.cmd` in their Startup folder in six months should
    not have to search the internet to find out what it is or how to stop it.
    """
    assert autostart.MARKER in body
    assert "haze autostart disable" in body


@pytest.mark.parametrize("body", [autostart.startup_body(EXE), autostart.console_body(EXE)])
def test_generated_files_use_crlf(body: str) -> None:
    """Batch files are parsed by cmd.exe, which is entitled to expect CRLF."""
    assert "\r\n" in body
    assert not body.replace("\r\n", "").count("\n")


# --- paths that would produce a batch file meaning something else -------------

def test_a_percent_in_the_path_is_refused_rather_than_expanded() -> None:
    """`%` expands inside double quotes in a batch file, unlike & ^ | and !.

    A profile at C:\\Users\\100%bob would silently resolve to something else.
    Refusing with the path in the message beats writing a file that starts the
    wrong program.
    """
    with pytest.raises(autostart.AutostartError, match="cannot carry safely"):
        autostart.validate_exe_path(Path(r"C:\Users\100%bob\haze.exe"))


@pytest.mark.parametrize("name", ["Ben & Kate", "caret^user", "bang!user", "pipe|user"])
def test_characters_that_quoting_already_neutralises_are_allowed(name: str) -> None:
    """These are legal in Windows file names and harmless inside the quotes.

    Rejecting them would break real people to guard against nothing.
    """
    autostart.validate_exe_path(Path(rf"C:\Users\{name}\haze.exe"))


# --- the round trip ----------------------------------------------------------

def test_enable_then_disable_leaves_no_trace(env: dict[str, str]) -> None:
    written = autostart.enable(env, EXE)
    assert len(written) == 2
    assert all(p.exists() for p in written)
    assert all(present for _, present in autostart.status(env))

    removed, foreign = autostart.disable(env)
    assert sorted(removed) == sorted(written)
    assert foreign == []
    assert not any(p.exists() for p in written)
    assert not any(present for _, present in autostart.status(env))


def test_enable_is_idempotent(env: dict[str, str]) -> None:
    """Running it twice is what someone does when unsure it worked."""
    first = autostart.enable(env, EXE)
    second = autostart.enable(env, EXE)
    assert first == second
    # read_bytes, not read_text: universal newlines would translate the CRLFs
    # away on POSIX and quietly make this assertion weaker.  (Path.read_text
    # only grew a newline= argument in 3.13; this package supports 3.12.)
    assert first[0].read_bytes().decode("utf-8") == autostart.startup_body(EXE)


def test_disable_on_a_clean_machine_is_not_an_error(env: dict[str, str]) -> None:
    """Checking you already turned it off deserves an answer, not exit 1."""
    assert autostart.disable(env) == ([], [])


def test_disable_refuses_to_delete_a_file_haze_did_not_write(env: dict[str, str]) -> None:
    """Someone else's Haze.cmd is not ours to remove.

    The Startup folder is shared by everything on the machine.  A name collision
    must not turn `haze autostart disable` into a delete of somebody's own
    script.
    """
    theirs = autostart.startup_dir(env) / autostart.STARTUP_FILENAME
    theirs.write_text("echo my own script\r\n", encoding="utf-8")

    removed, foreign = autostart.disable(env)
    assert removed == []
    assert foreign == [theirs]
    assert theirs.exists()


def test_a_missing_startup_folder_is_reported_not_created(env: dict[str, str]) -> None:
    """If the folder is not there, our idea of where it lives is wrong.

    Creating it would hide that: Windows reads the real one, so the shortcut
    would sit in a directory nothing ever looks at while `enable` reported
    success.  The message names the path and how to check it.
    """
    autostart.startup_dir(env).rmdir()
    with pytest.raises(autostart.AutostartError, match="shell:startup"):
        autostart.enable(env, EXE)
