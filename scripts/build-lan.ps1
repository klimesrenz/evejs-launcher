param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    & $Python -m venv .venv-lan
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
    $py = Join-Path $root '.venv-lan\Scripts\python.exe'
    & $py -m pip install -r requirements-build.txt -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $savedAppData = $env:APPDATA
    $savedQt = $env:QT_QPA_PLATFORM
    try {
        $env:APPDATA = Join-Path $root 'build\lan-check-appdata'
        $env:QT_QPA_PLATFORM = 'offscreen'
        & $py -m compileall -q lan_main.py src/lan.py src/lan_window.py src/core/lan_api.py src/core/lan_client.py
        if ($LASTEXITCODE -ne 0) { throw 'LAN syntax check failed.' }
        & $py -m pytest -q tests/test_config.py tests/test_launcher.py tests/test_profiles.py
        if ($LASTEXITCODE -ne 0) { throw 'Existing launcher checks failed.' }
        & $py -c "from PyQt6.QtWidgets import QApplication; from src.lan_window import Window; a=QApplication([]); w=Window(); w.show(); a.processEvents(); w.close()"
        if ($LASTEXITCODE -ne 0) { throw 'LAN UI check failed.' }
    } finally {
        $env:APPDATA = $savedAppData
        $env:QT_QPA_PLATFORM = $savedQt
    }
    & $py -m PyInstaller --clean --noconfirm --onedir --windowed --name EveJS-LAN-Launcher --add-data 'src/core/lan_trust.ps1;src/core' lan_main.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    Copy-Item LAN.md dist/EveJS-LAN-Launcher/README-LAN.md
    Copy-Item LICENSE dist/EveJS-LAN-Launcher/LICENSE
    Copy-Item THIRD_PARTY_NOTICES.md dist/EveJS-LAN-Launcher/THIRD_PARTY_NOTICES.md
    Copy-Item licenses dist/EveJS-LAN-Launcher/licenses -Recurse -Force
    & $py scripts/package-lan.py
    if ($LASTEXITCODE -ne 0) { throw 'Package validation failed.' }
} finally { Pop-Location }
