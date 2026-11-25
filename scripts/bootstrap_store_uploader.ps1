[CmdletBinding()]
param(
    [string]$VenvDirectory = '.venv-store-uploader'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot
$python = Get-Command python -ErrorAction Stop
$venvPath = Join-Path $repoRoot $VenvDirectory
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $python.Source -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}

& $venvPython -m pip install -r (Join-Path $repoRoot 'requirements-store-uploader.txt')
if ($LASTEXITCODE -ne 0) { throw 'Local Store uploader dependency installation failed.' }

# Keep the -c payload whitespace- and quote-free. This avoids native argument
# parsing differences in Windows PowerShell 5.1 when forwarding embedded quotes.
& $venvPython -c 'import playwright.sync_api;assert callable(playwright.sync_api.sync_playwright)'
if ($LASTEXITCODE -ne 0) { throw 'Playwright runtime validation failed.' }

Write-Host 'Playwright runtime validation passed.' -ForegroundColor Green
Write-Host 'Store uploader Python environment is ready.' -ForegroundColor Green
Write-Host "Python: $venvPython"
Write-Host 'No browser binary was downloaded. The uploader attaches to the installed Microsoft Edge through local CDP.'
