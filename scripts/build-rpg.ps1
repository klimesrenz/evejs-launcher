param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    & $Python -m venv .venv-rpg
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required; cannot create the build environment.' }
    $venvPython = Join-Path $root '.venv-rpg\Scripts\python.exe'
    & $venvPython -m pip install -r requirements-build.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    # Tests use fixtures and an isolated profile, never the user's launcher settings.
    $savedAppData = $env:APPDATA
    $savedQtPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:APPDATA = Join-Path $root 'build\rpg-check-appdata'
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $venvPython -m pytest -q tests/test_config.py tests/test_update_asset_selection.py tests/test_launcher.py tests/test_server_launcher.py tests/test_service_lifecycle_worker.py tests/test_native_market_preflight_regressions.py tests/test_native_config_preflight.py tests/test_update_flow.py tests/test_mod_api_runtime_protocol.py tests/test_mod_updates.py
        if ($LASTEXITCODE -ne 0) { throw 'Launcher validation failed; build stopped.' }
    } finally {
        $env:APPDATA = $savedAppData
        $env:QT_QPA_PLATFORM = $savedQtPlatform
    }
    & $venvPython -m PyInstaller build.spec --clean --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    & $venvPython scripts/package-rpg.py
    if ($LASTEXITCODE -ne 0) { throw 'Package validation failed.' }
    Write-Host 'Ready: dist\EveJS-RPG-Launcher.zip'
} finally {
    Pop-Location
}
