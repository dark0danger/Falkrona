[CmdletBinding()]
param(
    [string]$HermesHome
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $HermesHome) {
    $HermesHome = Join-Path $projectRoot '.runtime/hermes/phase4/workspace-a'
}
$sourceDirectory = Join-Path $projectRoot 'infra/hermes/skills/social-media-graphic-design'
$targetDirectory = Join-Path $HermesHome 'skills/social-media-graphic-design'
New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
Copy-Item -Path (Join-Path $sourceDirectory '*') -Destination $targetDirectory -Recurse -Force
foreach ($relativePath in @('SKILL.md', 'references/design-policy.json')) {
    $source = Join-Path $sourceDirectory $relativePath
    $target = Join-Path $targetDirectory $relativePath
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
        throw "Hermes skill installation hash mismatch: $relativePath"
    }
}
Write-Output "Installed social-media-graphic-design: $targetDirectory"
