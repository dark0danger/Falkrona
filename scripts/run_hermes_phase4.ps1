$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$hermesCheckout = Join-Path $projectRoot '.dependencies/hermes-agent'
$pin = Get-Content -LiteralPath (Join-Path $projectRoot 'infra/hermes/pin.json') -Raw | ConvertFrom-Json

if (-not (Test-Path -LiteralPath (Join-Path $hermesCheckout '.git'))) {
    throw 'Hermes checkout is missing. Run scripts/prepare_hermes.ps1 first.'
}
Push-Location $hermesCheckout
try {
    if ((git rev-parse HEAD).Trim() -ne $pin.commit) {
        throw 'Hermes checkout does not match the pinned commit.'
    }
}
finally {
    Pop-Location
}
$env:HERMES_HOME = Join-Path $projectRoot '.runtime/hermes/spike-bootstrap'
$env:HERMES_RUNTIME_DIR = Join-Path $projectRoot '.runtime/hermes/tools'
Push-Location $projectRoot
try {
    uv run python (Join-Path $projectRoot 'scripts/run_hermes_phase4.py')
    if ($LASTEXITCODE -ne 0) { throw "Phase 4 Hermes proof failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
