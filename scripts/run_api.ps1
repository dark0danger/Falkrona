param([int]$Port = 8000)
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
& "$root\.venv\Scripts\python.exe" -m uvicorn apps.api.main:app --host 127.0.0.1 --port $Port --no-access-log
exit $LASTEXITCODE
