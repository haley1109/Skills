param([switch]$Offline)
$ErrorActionPreference = "Stop"
$pythonExe = (Get-Command python -ErrorAction Stop).Source
& $pythonExe -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$requirementsFile = if ($Offline) { 'requirements.txt' } else { 'requirements-online.txt' }
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot $requirementsFile)
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $Offline) {
    & $pythonExe (Join-Path $PSScriptRoot 'scripts/capture_single.py') --diagnose
    exit $LASTEXITCODE
}
