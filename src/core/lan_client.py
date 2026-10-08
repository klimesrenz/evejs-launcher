"""Explicit LAN preparation and launch of an existing offline EVE client."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import tempfile

from ..lan import CONFIG_DIR
from .lan_api import Client, Connection, LANError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_key(text, key, value):
    pattern = r'(?mi)^\s*' + re.escape(key) + r'\s*=.*$'
    if re.search(pattern, text):
        return re.sub(pattern, lambda _: key + '=' + value, text)
    return text.rstrip() + '\n' + key + '=' + value + '\n'


def start_text(client):
    raw = (client / 'start.ini').read_bytes()
    text = raw.decode('utf-8-sig')
    if not re.search(r'(?mi)^\s*build\s*=\s*3396210\s*$', text):
        raise LANError('Нужен подготовленный клиент build 3396210.')
    if not re.search(r'(?mi)^\s*cryptoPack\s*=\s*Placebo\s*$', text):
        raise LANError('Сначала подготовьте отдельный offline-клиент штатным ClientSETUP.')
    return raw, text


def closed_clients_required():
    from .overview_patch import is_eve_client_running
    if is_eve_client_running():
        raise LANError('Перед подготовкой или откатом закройте все клиенты EVE, включая RPG.')


def client_bundles(client):
    found = []
    pending = [client]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path == client / '.evejs-lan-backup':
                continue
            info = path.lstat()
            if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise LANError('Для подготовки нужна полная копия tq без вложенных junction/symlink.')
            if path.is_dir():
                pending.append(path)
            elif path.name.lower() == 'cacert.pem' and path.is_file():
                found.append(path)
    if not found:
        raise LANError('Не найдены клиентские cacert.pem.')
    return found


def trust_public_ca(ca_path):
    # Add the chosen CA without deleting another world's CA.
    from .platform import get_hidden_process_flags
    script = Path(__file__).resolve().parent / 'lan_trust.ps1'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(script), '-CertificatePath', str(ca_path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=30, **get_hidden_process_flags())
    if result.returncode:
        raise LANError('Windows не принял публичный игровой CA: ' + result.stderr[-1000:])


def prepare(client_path, connection: Connection):
    if os.name != 'nt':
        raise LANError('Подготовка игрового клиента выполняется на Windows.')
    client = Path(client_path).resolve(strict=True)
    if not connection.game_ca_pem:
        raise LANError('В файле подключения нет игрового CA; повторите Linux prepare и импорт.')
    closed_clients_required()
    from .launcher import _resolve_client_resource_cache
    from .platform import serialize_evejs_client_trust_and_spawn
    _resolve_client_resource_cache(client, str(client))
    with serialize_evejs_client_trust_and_spawn():
        closed_clients_required()
        raw, text = start_text(client)
        bundles = client_bundles(client)
        updated = patch_key(text, 'server', connection.host)
        if re.search(r'(?mi)^\s*serverip\s*=', updated):
            updated = patch_key(updated, 'serverip', connection.host)
        files = {'start.ini': (raw, updated.encode('utf-8'))}
        ca = connection.game_ca_pem.replace('\r\n', '\n').strip()
        for bundle in bundles:
            before = bundle.read_bytes()
            normalized = before.decode('utf-8-sig').replace('\r\n', '\n')
            after = before if ca in normalized else (normalized.rstrip() + '\n' + ca + '\n').encode()
            files[str(bundle.relative_to(client))] = (before, after)
        receipt = client / '.evejs-lan-preparation.json'
        backup = client / '.evejs-lan-backup'
        if receipt.exists():
            old = json.loads(receipt.read_text())
            if old.get('host') != connection.host or old.get('ca_sha256') != digest(ca.encode()):
                raise LANError('Клиент подготовлен для другого адреса/CA: сначала выполните откат.')
            if set(old['files']) != set(files):
                raise LANError('Набор сертификатных файлов изменился; сначала откатите подготовку.')
            for name, values in old['files'].items():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise LANError('Повреждён receipt.')
                if digest((client / name).read_bytes()) not in (values['before'], values['after']):
                    raise LANError('Клиент изменён после подготовки: ' + name)
            # Retry a partially applied preparation using the original receipt.
            record = old
        else:
            if backup.exists():
                raise LANError('Есть backup без receipt; сохраните его и восстановите подготовку вручную.')
            record = {'schema': 1, 'host': connection.host, 'ca_sha256': digest(ca.encode()),
                      'files': {name: {'before': digest(before), 'after': digest(after)}
                                for name, (before, after) in files.items()}}
            for name, (before, _) in files.items():
                target = backup / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
            receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ca_path = CONFIG_DIR / ('game-ca-' + digest(ca.encode()) + '.pem')
        ca_path.write_text(ca + '\n', encoding='utf-8')
        trust_public_ca(ca_path)
        for name, (_, after) in files.items():
            target = client / name
            if target.read_bytes() != after:
                temporary = target.with_name(target.name + '.lan-tmp')
                temporary.write_bytes(after)
                temporary.replace(target)
        return 'LAN-клиент подготовлен. Исходные файлы сохранены в .evejs-lan-backup.'


def restore(client_path):
    from .platform import serialize_evejs_client_trust_and_spawn
    with serialize_evejs_client_trust_and_spawn():
        return _restore(client_path)


def _restore(client_path):
    closed_clients_required()
    client = Path(client_path).resolve(strict=True)
    receipt = client / '.evejs-lan-preparation.json'
    record = json.loads(receipt.read_text())
    backup = client / '.evejs-lan-backup'
    for name, values in record['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise LANError('Повреждён receipt.')
        if digest((client / name).read_bytes()) not in (values['before'], values['after']):
            raise LANError('После подготовки изменён файл; автоматический откат запрещён: ' + name)
        if digest((backup / name).read_bytes()) != values['before']:
            raise LANError('Повреждена резервная копия: ' + name)
    for name in record['files']:
        target = client / name
        temporary = target.with_name(target.name + '.lan-restore-tmp')
        shutil.copy2(backup / name, temporary)
        temporary.replace(target)
    receipt.unlink()
    shutil.rmtree(backup)
    return 'Файлы клиента восстановлены. Публичный CA оставлен в Windows trust для других профилей.'


def launch(client_path, profile, connection):
    process = launch_process(client_path, profile, connection)
    return f'Клиент запущен: профиль {profile}, PID {process.pid}. Вход в аккаунт выполняется в игре.'


def launch_process(client_path, profile, connection, *, intent=None):
    from .platform import serialize_evejs_client_trust_and_spawn
    with serialize_evejs_client_trust_and_spawn():
        return _launch(client_path, profile, connection, intent=intent)


def _launch(client_path, profile, connection, *, intent=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', profile):
        raise LANError('Имя профиля: 1–40 английских букв, цифр, _ или -.')
    status = Client(connection).status()
    if status.get('services', {}).get('game', {}).get('state') != 'running':
        raise LANError('Game ещё не готов; сначала запустите сервер.')
    client = Path(client_path).resolve(strict=True)
    _, text = start_text(client)
    if not re.search(r'(?mi)^\s*server\s*=\s*' + re.escape(connection.host) + r'\s*$', text):
        raise LANError('Сначала нажмите «Подготовить LAN-клиент».')
    record = json.loads((client / '.evejs-lan-preparation.json').read_text())
    ca = connection.game_ca_pem.replace('\r\n', '\n').strip()
    if record.get('host') != connection.host or record.get('ca_sha256') != digest(ca.encode()):
        raise LANError('Подготовка не соответствует выбранному Linux-серверу.')
    for name, value in record['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or digest((client / name).read_bytes()) != value['after']:
            raise LANError('Клиентские файлы изменились после подготовки; повторите её.')
    from .profiles import _ensure_profile_junction
    from .launcher import _resolve_client_resource_cache, _apply_legacy_identity_compatibility
    from .platform import get_client_exe_path, launch_eve_client, serialize_evejs_client_trust_and_spawn
    arguments = ('/port:26000', f'/resfileserver=http://{connection.host}:26002/resfiles/')
    if intent is not None:
        from .lan_characters import account_profile, login_arguments
        permit = Client(connection).launch_check(intent.username, intent.character_id)
        arguments += login_arguments(client, connection, intent, permit)
        profile = account_profile(connection, permit['account_id'])
    directory = CONFIG_DIR / 'Profiles' / profile
    directory.mkdir(parents=True, exist_ok=True)
    junction = directory / 'tq'
    _ensure_profile_junction(junction, client)
    cache = _resolve_client_resource_cache(junction, str(client))
    exe = get_client_exe_path(junction)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(('EVEJS_', 'AUTOMINING_'))
           and k.upper() not in ('NODE_OPTIONS', 'NODE_PATH', 'EO_REMOTEFILECACHEFOLDER')}
    proxy = f'http://{connection.host}:26002'
    for key in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','all_proxy','ALL_PROXY'):
        env[key] = proxy
    for key in ('no_proxy','NO_PROXY','EVEJS_NO_PROXY'):
        env[key] = '127.0.0.1,localhost,::1,' + connection.host
    ca_path = CONFIG_DIR / ('game-ca-' + digest(ca.encode()) + '.pem')
    if not ca_path.is_file() or ca_path.read_text().strip() != ca:
        raise LANError('Файл игрового CA отсутствует или изменён; повторите подготовку.')
    trust_public_ca(ca_path)  # Add-only: another launcher may have removed this world's CA.
    for key in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
        env[key] = str(ca_path)
    env.update(SSL_CERT_DIR='', EO_REMOTEFILECACHEFOLDER=str(cache), EVEJS_PROXY_LOCAL_INTERCEPT='1',
               EVEJS_PROXY_UNHANDLED_HOST_POLICY='block', EVE_CLIENT_SENTRY_DSN='', LD_OFFLINE='true',
               AUTOMINING_CLIENT_DELIVERY='login-v1', AUTOMINING_PROFILE_SETTINGS='{"apply":false}')
    _apply_legacy_identity_compatibility(env)
    with serialize_evejs_client_trust_and_spawn():
        process = launch_eve_client(exe, env, exe.parent,
            arguments=arguments)
    return process
