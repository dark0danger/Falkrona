[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$brandpilotRoot = Split-Path -Parent $PSScriptRoot
$hermesCheckout = Join-Path $brandpilotRoot '.dependencies/hermes-agent'
$hermesPin = Get-Content -LiteralPath (Join-Path $brandpilotRoot 'infra/hermes/pin.json') -Raw | ConvertFrom-Json

if (-not (Test-Path -LiteralPath (Join-Path $hermesCheckout '.git'))) {
    throw 'Hermes checkout is missing. Run scripts/prepare_hermes.ps1 first.'
}

Push-Location $hermesCheckout
try {
    $actual = (git rev-parse HEAD).Trim()
    if ($actual -ne $hermesPin.commit) {
        throw "Hermes checkout mismatch: expected $($hermesPin.commit), got $actual"
    }
    $env:HERMES_HOME = Join-Path $brandpilotRoot '.runtime/hermes/spike-bootstrap'
    $env:HERMES_RUNTIME_DIR = Join-Path $brandpilotRoot '.runtime/hermes/tools'
    . .\activate.ps1
    python (Join-Path $brandpilotRoot 'scripts/run_hermes_spike.py')
    if ($LASTEXITCODE -ne 0) {
        throw "Hermes spike failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
