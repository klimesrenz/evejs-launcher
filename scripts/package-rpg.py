"""Package only the complete PyInstaller output, never a server or local profile."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

root = Path(__file__).resolve().parent.parent
output = root / "dist" / "EveJS-RPG-Launcher"
required = ["EveJS-RPG-Launcher.exe", "_internal/VERSION", "_internal/LICENSE",
            "_internal/RPG.md", "_internal/THIRD_PARTY_NOTICES.md",
            "_internal/PyQt6/Qt6/plugins/platforms/qwindows.dll"]
for name in required:
    if not (output / name).is_file():
        raise SystemExit(f"Incomplete Windows build: {name}")
version = (root / "VERSION").read_text().strip()
if (output / "_internal/VERSION").read_text().strip() != version:
    raise SystemExit("The bundled version does not match the source.")
try:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
except (OSError, subprocess.CalledProcessError):
    commit, dirty = "source-archive", None
manifest = {"version": version, "source_commit": commit, "source_dirty": dirty,
            "upstream": "V0nCleef/evejs-launcher", "upstream_version": "1.0.69",
            "files": {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(output.rglob("*")) if p.is_file() and p.name != "RPG-BUILD.json"}}
(output / "RPG-BUILD.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
archive = Path(shutil.make_archive(str(root / "dist/EveJS-RPG-Launcher"), "zip", output.parent, output.name))
archive.with_suffix(".zip.sha256").write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="ascii")
print(archive)
