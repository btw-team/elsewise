param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"
$InstallerPath = (Resolve-Path $InstallerPath).Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\Elsewise"
$Uninstaller = Join-Path $InstallDir "unins000.exe"
$Cli = Join-Path $InstallDir "elsewise.exe"
$CliPath = Join-Path $InstallDir "bin"

& $InstallerPath /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="addtopath"
if ($LASTEXITCODE -ne 0) { throw "Installer failed with exit code $LASTEXITCODE" }
if (-not (Test-Path $Cli)) { throw "Installed CLI is missing: $Cli" }

& $Cli --version
if ($LASTEXITCODE -ne 0) { throw "Installed CLI smoke test failed" }
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ';') -notcontains $CliPath) {
    throw "Installer did not add the public CLI directory to user PATH"
}

& $Uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
if ($LASTEXITCODE -ne 0) { throw "Uninstaller failed with exit code $LASTEXITCODE" }
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ';') -contains $CliPath) {
    throw "Uninstaller did not remove the public CLI directory from user PATH"
}
