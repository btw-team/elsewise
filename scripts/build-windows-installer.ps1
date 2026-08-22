$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Version = & "$Root\.venv\Scripts\python.exe" "$Root\scripts\version.py"
$Links = Get-Content "$Root\shared\external-links.json" -Raw | ConvertFrom-Json
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) {
    $Iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $Iscc)) {
    throw "Inno Setup 6 was not found"
}
& $Iscc "/DAppVersion=$Version" "/DProjectUrl=$($Links.project)" "/DReleasesUrl=$($Links.releases)" "$Root\packaging\windows\elsewise.iss"
