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

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $Process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "$Description failed with exit code $($Process.ExitCode)"
    }
}

Invoke-CheckedProcess `
    -FilePath $InstallerPath `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=addtopath") `
    -Description "Installer"
if (-not (Test-Path $Cli)) { throw "Installed CLI is missing: $Cli" }
if (-not (Test-Path $Uninstaller)) { throw "Uninstaller is missing: $Uninstaller" }

& $Cli --version
if ($LASTEXITCODE -ne 0) { throw "Installed CLI smoke test failed" }
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ';') -notcontains $CliPath) {
    throw "Installer did not add the public CLI directory to user PATH"
}

Invoke-CheckedProcess `
    -FilePath $Uninstaller `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
    -Description "Uninstaller"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ';') -contains $CliPath) {
    throw "Uninstaller did not remove the public CLI directory from user PATH"
}
