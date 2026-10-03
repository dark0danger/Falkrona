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
& "$root\.venv\Scripts\python.exe" -m apps.worker.main @args
exit $LASTEXITCODE
