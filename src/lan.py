"""Independent LAN application identity and user-owned settings."""
import json
import os
from pathlib import Path

VERSION = '1.0.69'
LAN_VERSION = '0.1.1'
APP_NAME = 'EveJS-LAN-Launcher'
CONFIG_DIR = Path(os.environ.get('APPDATA') or Path.home() / '.config') / APP_NAME


def load_settings():
    try:
        value = json.loads((CONFIG_DIR / 'settings.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'client_path': '', 'profiles': ['Main'], 'pending_job': ''}
    if not isinstance(value, dict) or not isinstance(value.get('profiles'), list):
        raise ValueError('Повреждены настройки LAN-лаунчера.')
    return value


def save_settings(value):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = CONFIG_DIR / 'settings.json'
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(target)
