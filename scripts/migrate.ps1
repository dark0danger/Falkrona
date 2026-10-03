$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$envFile = Join-Path $root '.env'
if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#')) {
            $name, $value = $line -split '=', 2
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}
if (-not $env:BRANDPILOT_DATABASE_URL) {
    $env:BRANDPILOT_DATABASE_URL = "postgresql+psycopg://brandpilot:brandpilot@127.0.0.1:5432/brandpilot"
}
& "$root\.venv\Scripts\python.exe" -m alembic upgrade head
exit $LASTEXITCODE
