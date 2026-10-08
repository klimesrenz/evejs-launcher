from pathlib import Path
import hashlib
import json
import subprocess
import zipfile
root=Path(__file__).resolve().parents[1]
folder=root/'dist/EveJS-LAN-Launcher'
assert (folder/'EveJS-LAN-Launcher.exe').is_file()
assert (folder/'_internal/src/core/lan_trust.ps1').is_file()
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
(folder/'BUILD.json').write_text(json.dumps({'version':'0.1.0','compatibility_version':'1.0.69','source_commit':revision},indent=2))
archive=root/'dist/EveJS-LAN-Launcher.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    for path in sorted(folder.rglob('*')):
        if path.is_file():output.write(path,path.relative_to(folder.parent))
with zipfile.ZipFile(archive) as output:assert output.testzip() is None
archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(archive)
