# Smart GUI Launcher
# Bootstraps the virtual environment, installs/updates dependencies,
# checks GitHub for a newer release (auto-update) and finally starts the
# graphical interface (src/gui.py) with no lingering console window.

# NOTE: kept at "Continue" (not "Stop") on purpose. The python/pip calls below
# write to stderr for ordinary informational output; under Windows PowerShell
# 5.1, redirecting a native command's stderr while ErrorActionPreference is
# "Stop" turns every such line into a terminating NativeCommandError. Control
# flow here is driven explicitly via $LASTEXITCODE / Test-Path checks instead.
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path
$VenvPath = "$ProjectRoot\.venv"
$PythonExe = "$VenvPath\Scripts\python.exe"
$PythonwExe = "$VenvPath\Scripts\pythonw.exe"
$PipExe = "$VenvPath\Scripts\pip.exe"
$UpdaterScript = "$ProjectRoot\launcher\updater.py"
$GuiScript = "$ProjectRoot\src\gui.py"
$ReqFile = "$ProjectRoot\requirements.txt"
$VersionFile = "$ProjectRoot\src\ciphervault\__init__.py"
$LogFile = "$ProjectRoot\launcher\gui_launcher.log"

function Write-Log($message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogFile -Value "[$stamp] $message" -Encoding utf8
}

function Invoke-Logged($exe, $exeArgs) {
    # Merge stdout+stderr into the log file without letting PowerShell turn
    # native stderr lines into terminating errors (see note above). Error
    # stream entries arrive as ErrorRecord objects, not plain strings, so
    # their real text has to be pulled out explicitly or the log just shows
    # "System.Management.Automation.RemoteException".
    & $exe @exeArgs 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            Add-Content -Path $LogFile -Value $_.Exception.Message -Encoding utf8
        } else {
            Add-Content -Path $LogFile -Value $_ -Encoding utf8
        }
    }
    return $LASTEXITCODE
}

$LauncherVersion = "Unknown"
if (Test-Path $VersionFile) {
    $Content = Get-Content $VersionFile -Raw
    if ($Content -match '__version__\s*=\s*["'']([^"'']+)["'']') {
        $LauncherVersion = $Matches[1]
    }
}
Write-Log "CipherVault GUI launcher starting (v$LauncherVersion)"

$bootstrapOk = $true

# 1. Bootstrap: create the virtual environment on first run
if (-not (Test-Path $VenvPath)) {
    Write-Log "No .venv found; creating one."
    Invoke-Logged "python" @("-m", "venv", $VenvPath) | Out-Null
    if (-not (Test-Path $PythonExe)) {
        Write-Log "FATAL: python was not found on PATH or venv creation failed."
        $bootstrapOk = $false
    } elseif (Test-Path $ReqFile) {
        Invoke-Logged $PipExe @("install", "-r", $ReqFile) | Out-Null
        Write-Log "Environment created."
    }
}

if ($bootstrapOk) {
    # Make sure auto-update + GUI dependencies exist even if requirements.txt predates them
    Invoke-Logged $PipExe @("install", "requests", "packaging", "customtkinter", "tkinterdnd2", "Pillow") | Out-Null

    # 2. Auto-update: check GitHub, update in place if a newer version exists
    if (Test-Path $UpdaterScript) {
        Write-Log "Checking for updates..."
        $checkCode = Invoke-Logged $PythonExe @($UpdaterScript, "--check-only")
        if ($checkCode -eq 1) {
            Write-Log "Update available. Applying..."
            $updateCode = Invoke-Logged $PythonExe @($UpdaterScript, "--perform-update")
            if ($updateCode -eq 0) {
                Invoke-Logged $PipExe @("install", "-r", $ReqFile) | Out-Null
                $Content = Get-Content $VersionFile -Raw
                if ($Content -match '__version__\s*=\s*["'']([^"'']+)["'']') {
                    $LauncherVersion = $Matches[1]
                }
                Write-Log "Update applied successfully (now v$LauncherVersion)."
            } else {
                Write-Log "Update failed; continuing with local version."
            }
        } else {
            Write-Log "Already up to date (or offline)."
        }
    }
} else {
    Write-Log "Skipping dependency/update steps due to bootstrap failure."
}

# 3. Launch the GUI with no console window attached
Write-Log "Starting GUI ($GuiScript)"
Start-Process -FilePath $PythonwExe -ArgumentList "`"$GuiScript`"" -WorkingDirectory $ProjectRoot
