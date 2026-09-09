#Requires -Version 5.1
<#
    Haze -- Windows bootstrap.

    Installs the `haze` command on this machine and nothing else.  Read it
    before you run it; that is the entire reason it is a script you can open in
    Notepad rather than an .exe you cannot.

    What it does, in order:
      1. checks this is Windows and you are not running as administrator
      2. installs uv (https://astral.sh/uv) if you do not already have it
      3. installs Python 3.12 through uv, if you do not already have one
      4. installs haze-agent from PyPI, which provides the `haze` command
      5. puts it on your PATH and proves it runs

    What it does NOT do:
      * ask for administrator.  Everything lands in your own user profile.
      * change your execution policy.  The documented one-liner uses
        -ExecutionPolicy Bypass, which applies to that one PowerShell process
        and nothing else.
      * install a service, a driver, or anything that starts by itself.  If you
        want Haze to start when you log in, that is a separate, visible step:
        `haze autostart enable`, undone by `haze autostart disable`.

    If you already have uv, you do not need this script at all:

        uv tool install haze-agent

    That is the whole install.  This file exists only so that someone who has
    never opened PowerShell does not have to know that.

    Source: https://github.com/CodeMaster747/Haze
#>

# Every line this script prints is for a person reading a console, which is what
# Write-Host is for.  Write-Output would be actively wrong: the documented
# invocation is `irm ... | iex`, so anything on the success pipeline is returned
# to the caller as a value rather than shown.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'This script talks to a human at a console, not a pipeline.')]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Which stage we are in, so the failure handler can say what state the machine
# was left in rather than printing a bare exception.
$script:Stage = 'starting up'

function Step([string]$Name, [string]$Message) {
    $script:Stage = $Name
    Write-Host ''
    Write-Host "  $Message" -ForegroundColor Cyan
}

function Note([string]$Message) {
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Fail([string]$Message) {
    throw $Message
}

function Add-ToSessionPath([string]$Dir) {
    if (($env:PATH -split ';') -notcontains $Dir) {
        $env:PATH = "$Dir;$env:PATH"
    }
}

try {
    Write-Host ''
    Write-Host '  Haze' -ForegroundColor White
    Write-Host '  Pool your own machines into a private compute network.' -ForegroundColor DarkGray

    # --- 1. preflight --------------------------------------------------------
    Step 'preflight' 'Checking this machine...'

    # $IsWindows exists only on PowerShell 6+; on Windows PowerShell 5.1 the
    # absence of it is itself the answer.
    if ((Test-Path variable:IsWindows) -and -not $IsWindows) {
        Fail "This script installs Haze on Windows. On macOS and Linux, run: uv tool install haze-agent"
    }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        # A warning, not a failure: it will work, it just installs for the wrong
        # person.  Better to say so than to refuse and be worked around.
        Write-Host ''
        Write-Host '  Warning: this PowerShell is running as administrator.' -ForegroundColor Yellow
        Write-Host '  Haze does not need it, and installing this way puts the `haze`' -ForegroundColor Yellow
        Write-Host '  command in the administrator profile rather than yours.' -ForegroundColor Yellow
        Write-Host '  Close this window and open PowerShell normally instead.' -ForegroundColor Yellow
        Write-Host ''
    }
    Note "Windows, PowerShell $($PSVersionTable.PSVersion)"

    # --- 2. uv ---------------------------------------------------------------
    Step 'installing uv' 'Looking for uv...'

    # uv installs into %USERPROFILE%\.local\bin, and so does `uv tool install`.
    # Adding it to *this process* means the rest of the script can call uv and
    # haze immediately; step 5 is what makes that stick for future terminals.
    # Computed here rather than at the top of the file so that it is inside the
    # try -- anything that can fail belongs where the failure handler can
    # explain it, and a bare exception traceback is exactly what this script
    # exists to spare someone.
    $BinDir = Join-Path $env:USERPROFILE '.local\bin'
    Add-ToSessionPath $BinDir

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Note "already installed: $((Get-Command uv).Source)"
    } else {
        Note 'not found, installing it from https://astral.sh/uv'
        # Astral's own installer, run the way they document it -- but in a child
        # process rather than piped into this one.  Three reasons, all of them
        # bugs avoided rather than style:
        #   * this script runs under Set-StrictMode -Version Latest and
        #     $ErrorActionPreference = 'Stop'.  Invoke-Expression would run
        #     their script in *our* scope, under settings it was never written
        #     against, and an uninitialised variable that is harmless in their
        #     script would become a fatal error in ours.
        #   * -ExecutionPolicy Bypass on the child means this works whatever the
        #     machine's policy is, without changing that policy for anything else.
        #   * a child process gives an exit code to check, instead of guessing
        #     from whether an exception escaped.
        # powershell.exe (Windows PowerShell 5.1) is present on every Windows
        # 10 and 11 machine, which pwsh.exe is not.
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
            "Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression"
        if ($LASTEXITCODE -ne 0) { Fail "The uv installer failed (exit $LASTEXITCODE)." }
        Add-ToSessionPath $BinDir

        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Fail @"
uv was installed but is still not on PATH, so this script cannot continue.
Close this window, open a new PowerShell, and run this script again -- the new
window will pick up the PATH change.
"@
        }
        Note "installed: $((Get-Command uv).Source)"
    }

    # --- 3. python -----------------------------------------------------------
    # Explicit rather than relying on uv fetching one implicitly. haze-agent
    # needs >=3.12,<3.14, this machine may have no Python at all, and if this is
    # the step that fails the message should say "Python".
    Step 'installing Python' 'Making sure Python 3.12 is available...'
    uv python install 3.12
    if ($LASTEXITCODE -ne 0) { Fail "uv could not install Python 3.12 (exit $LASTEXITCODE)." }

    # --- 4. haze -------------------------------------------------------------
    Step 'installing haze-agent' 'Installing Haze...'
    uv tool install --python 3.12 haze-agent
    if ($LASTEXITCODE -ne 0) { Fail "uv could not install haze-agent (exit $LASTEXITCODE)." }

    # --- 5. PATH -------------------------------------------------------------
    # Writes the User-scope environment, which is why no administrator is
    # needed. Without it `haze` works in this window and nowhere else.
    Step 'updating PATH' 'Putting haze on your PATH...'
    uv tool update-shell
    if ($LASTEXITCODE -ne 0) { Fail "uv could not update your PATH (exit $LASTEXITCODE)." }

    # Ask uv where it actually put the executable rather than assuming it went
    # to the default. It honours UV_TOOL_BIN_DIR, and a wrong guess here turns
    # "installed successfully" into "command not found" in the very next step.
    $toolBin = (uv tool dir --bin | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and $toolBin) {
        Add-ToSessionPath $toolBin
        Note "haze is in $toolBin"
    } else {
        Add-ToSessionPath $BinDir
    }

    # --- 6. prove it -----------------------------------------------------------
    Step 'verifying' 'Checking it works...'
    if (-not (Get-Command haze -ErrorAction SilentlyContinue)) {
        Fail @"
haze was installed but the command is not on PATH.
Close this window, open a new PowerShell, and type: haze version
"@
    }
    $version = (haze version) -join ' '
    if ($LASTEXITCODE -ne 0) { Fail "haze is installed but did not run (exit $LASTEXITCODE)." }
    Note $version

    # --- done ----------------------------------------------------------------
    Write-Host ''
    Write-Host '  Haze is installed.' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Start it, and open the dashboard:' -ForegroundColor White
    Write-Host '      haze up'
    Write-Host ''
    Write-Host '  Start it automatically every time you log in:' -ForegroundColor White
    Write-Host '      haze autostart enable'
    Write-Host '  and to stop it doing that again:' -ForegroundColor White
    Write-Host '      haze autostart disable'
    Write-Host ''
    Write-Host '  To lend this machine to your other computer, run `haze pair --serve`' -ForegroundColor DarkGray
    Write-Host '  here and `haze pair --host <this-pc>` there, then check the six digits' -ForegroundColor DarkGray
    Write-Host '  and four words match on both screens before confirming.' -ForegroundColor DarkGray
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host "  Install failed while $script:Stage." -ForegroundColor Red
    Write-Host ''
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''

    # Failing preflight means nothing was attempted, so there is no state to
    # report and re-running will not help -- the message above already says what
    # to do instead.  Reporting "uv installed, haze installed" here would be
    # true, irrelevant, and confusing directly under the word "failed".
    if ($script:Stage -eq 'preflight') { exit 1 }

    # Past preflight this spans two installers, so it cannot be atomic.  Rather
    # than pretend otherwise, say exactly what is on the machine now.
    $uvHere = [bool](Get-Command uv -ErrorAction SilentlyContinue)
    $hazeHere = [bool](Get-Command haze -ErrorAction SilentlyContinue)

    Write-Host '  State of this machine now:' -ForegroundColor White
    Write-Host "      uv    $(if ($uvHere) { 'installed' } else { 'not installed' })"
    Write-Host "      haze  $(if ($hazeHere) { 'installed' } else { 'not installed' })"
    Write-Host ''
    if ($uvHere -and -not $hazeHere) {
        Write-Host '  uv is there but Haze is not. Run this script again, or just:' -ForegroundColor White
        Write-Host '      uv tool install haze-agent'
    } else {
        Write-Host '  Nothing was left half-configured that a re-run will not fix.' -ForegroundColor White
        Write-Host '  Run this script again, or report it with the message above:' -ForegroundColor White
        Write-Host '      https://github.com/CodeMaster747/Haze/issues'
    }
    Write-Host ''
    exit 1
}
