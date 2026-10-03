[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$brandpilotRoot = Split-Path -Parent $PSScriptRoot
$hermesPin = Get-Content -LiteralPath (Join-Path $brandpilotRoot 'infra/hermes/pin.json') -Raw | ConvertFrom-Json
$hermesCheckout = Join-Path $brandpilotRoot '.dependencies/hermes-agent'

if (-not (Test-Path -LiteralPath (Join-Path $hermesCheckout '.git'))) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $hermesCheckout) | Out-Null
    git clone --filter=blob:none --no-checkout $hermesPin.repository $hermesCheckout
}

Push-Location $hermesCheckout
try {
    git checkout --detach $hermesPin.commit
    $actual = (git rev-parse HEAD).Trim()
    if ($actual -ne $hermesPin.commit) {
        throw "Hermes checkout mismatch: expected $($hermesPin.commit), got $actual"
    }

    $env:HERMES_HOME = Join-Path $brandpilotRoot '.runtime/hermes/bootstrap'
    $env:HERMES_RUNTIME_DIR = Join-Path $brandpilotRoot '.runtime/hermes/tools'
    & (Join-Path $PSScriptRoot 'install_hermes_skills.ps1') -HermesHome $env:HERMES_HOME
    . .\activate.ps1
    hermes --version
    if ($LASTEXITCODE -ne 0) {
        throw "Hermes version check failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
