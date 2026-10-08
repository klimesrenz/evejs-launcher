"""LAN management transport: pinned TLS, direct connections, no redirects."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import hmac
import http.client
import ipaddress
import json
from pathlib import Path
import re
import ssl
import uuid

PRIVATE = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
MAX_RESPONSE = 1024 * 1024


class LANError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, repr=False)
class Connection:
    host: str
    port: int
    token: str
    certificate_pem: str
    certificate_sha256: str
    game_ca_pem: str = ""

    @classmethod
    def parse(cls, value):
        fields = {'schema', 'host', 'port', 'token', 'certificate_pem', 'certificate_sha256'}
        if not isinstance(value, dict) or set(value) not in (fields, fields | {'game_ca_pem'}) or type(value['schema']) is not int or value['schema'] != 1:
            raise LANError('Неподдерживаемый файл подключения.')
        try:
            address = ipaddress.IPv4Address(value['host'])
        except (ValueError, TypeError):
            raise LANError('Ожидается IPv4-адрес Linux-сервера.') from None
        if not isinstance(value['host'], str) or not any(address in network for network in PRIVATE):
            raise LANError('Сервер должен находиться в частной LAN-сети RFC1918.')
        if type(value['port']) is not int or value['port'] != 26080:
            raise LANError('Ожидается порт управления 26080.')
        for field in ('token', 'certificate_sha256'):
            if not isinstance(value[field], str) or not re.fullmatch('[0-9a-f]{64}', value[field]):
                raise LANError('Неверный ключ/отпечаток в файле подключения.')
        pem = value['certificate_pem']
        if (not isinstance(pem, str) or len(pem) > 8192 or pem.count('-----BEGIN CERTIFICATE-----') != 1
                or 'PRIVATE KEY' in pem):
            raise LANError('Ожидается один публичный сертификат API.')
        try:
            digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
        except (ValueError, TypeError):
            raise LANError('Повреждён сертификат API.') from None
        if not hmac.compare_digest(digest, value['certificate_sha256']):
            raise LANError('Отпечаток сертификата API не совпадает.')
        game_ca = value.get('game_ca_pem', '')
        if game_ca:
            if not isinstance(game_ca, str) or len(game_ca) > 8192 or game_ca.count('-----BEGIN CERTIFICATE-----') != 1 or 'PRIVATE KEY' in game_ca:
                raise LANError('Неверный публичный игровой CA.')
            try:
                ssl.PEM_cert_to_DER_cert(game_ca)
            except (ValueError, TypeError):
                raise LANError('Повреждён игровой CA.') from None
        return cls(str(address), value['port'], value['token'], pem, digest, game_ca)

    @classmethod
    def read(cls, path: Path):
        with Path(path).open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise LANError('Файл подключения слишком большой.')
        try:
            return cls.parse(json.loads(raw))
        except (ValueError, UnicodeError):
            raise LANError('Повреждён JSON подключения.') from None


class Client:
    def __init__(self, connection: Connection, *, timeout=8):
        self.connection = connection
        self.timeout = timeout
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cadata=connection.certificate_pem)
        # No OS trust roots: this connection trusts only its imported certificate.

    def _request(self, method, path, value=None):
        config = self.connection
        connection = http.client.HTTPSConnection(config.host, config.port, timeout=self.timeout, context=self.context)
        body = json.dumps(value).encode() if value is not None else None
        try:
            connection.connect()
            digest = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(digest, config.certificate_sha256):
                raise LANError('Сертификат Linux-сервера изменился. Требуется новый файл подключения.')
            # Authorization is sent only after the TLS handshake and exact pin check.
            connection.request(method, path, body=body,
                               headers={'Authorization': 'Bearer ' + config.token,
                                        'Accept': 'application/json', 'Content-Type': 'application/json'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise LANError('Перенаправление API запрещено.')
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise LANError('Слишком большой ответ API.')
            if response.getheader('Content-Type', '').split(';', 1)[0].strip() != 'application/json':
                raise LANError('Ожидается JSON от API LinuxNative.')
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise LANError('Повреждён ответ API.') from None
            if not isinstance(result, dict):
                raise LANError('Неподдерживаемый ответ API.')
            if response.status not in (200, 202):
                detail = str(result.get('error', 'Ошибка API.'))[:500]
                raise LANError(f'HTTP {response.status}: {detail}', status=response.status)
            return result
        except (OSError, http.client.HTTPException) as error:
            # No URL/token/headers in exception messages shown to users.
            raise LANError('Нет подтверждённого ответа Linux-сервера (' + type(error).__name__ + '). Проверьте состояние перед повторной командой.') from None
        finally:
            connection.close()

    def status(self):
        value = self._request('GET', '/v1/status')
        if value.get('schema') != 1:
            raise LANError('Версия API не поддерживается.')
        return value

    def logs(self, name):
        if name not in ('game', 'market'):
            raise LANError('Неизвестный журнал.')
        return self._request('GET', '/v1/logs/' + name)

    def action(self, name, request_id):
        if name not in ('start', 'stop', 'start-game', 'stop-game', 'start-market', 'stop-market'):
            raise LANError('Неизвестная команда.')
        self._uuid(request_id)
        return self._request('POST', '/v1/actions', {'action': name, 'request_id': request_id})

    def job(self, identity):
        self._uuid(identity)
        return self._request('GET', '/v1/jobs/' + identity)

    @staticmethod
    def _uuid(identity):
        try:
            if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
                raise ValueError()
        except (ValueError, AttributeError):
            raise LANError('Неверный идентификатор операции.') from None
