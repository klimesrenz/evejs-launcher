"""LAN-only roster mapping, account profiles and native login validation."""
from __future__ import annotations
import hashlib
import math
from functools import partial
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
from .db import Account, Character
from .lan_api import LANError


def parse_roster(value):
    if value.get('schema') != 1 or not isinstance(value.get('accounts'), list) or len(value['accounts']) > 256:
        raise LANError('Неподдерживаемый список персонажей Linux.')
    result=[]; usernames=set(); ids=set(); characters=set()
    try:
        for row in value['accounts']:
            username=row['username']; identity=row['account_id']
            if (not isinstance(username,str) or not username or len(username)>160 or username in usernames
                    or type(identity) is not int or identity<=0 or identity in ids or type(row['banned']) is not bool):
                raise ValueError()
            usernames.add(username);ids.add(identity)
            account=Account(username,identity,'0',row['banned'])
            for item in row['characters']:
                character_id=item['char_id'];name=item['name']
                if type(character_id) is not int or character_id<=0 or character_id in characters or not isinstance(name,str) or not name or len(name)>160:
                    raise ValueError()
                characters.add(character_id)
                for field in ('isk','skill_points','ship_type_id','security_status'):
                    number=item[field]
                    if type(number) not in (int,float) or not math.isfinite(number):raise ValueError()
                if not isinstance(item['ship_name'],str) or not isinstance(item['location'],str):raise ValueError()
                account.characters.append(Character(character_id,name,isk=item['isk'],skill_points=item['skill_points'],
                    ship_name=item['ship_name'][:160],ship_type_id=int(item['ship_type_id']),
                    location=item['location'][:160],security_status=item['security_status']))
            result.append(account)
        if len(characters)>2048:raise ValueError()
        capability=value['login']
        if not isinstance(capability,dict) or type(capability.get('supported')) is not bool or not isinstance(capability.get('reason'),str):raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise LANError('Повреждён список персонажей Linux.') from None
    return result,capability


def account_profile(connection, account_id):
    identity=f'{connection.host}:{connection.certificate_sha256}:{account_id}'
    return 'Account_'+hashlib.sha256(identity.encode()).hexdigest()[:24]


def login_arguments(client, connection, intent, permit):
    from .client_autologin import build_auto_login_arguments, inspect_client_auto_login_capability
    if (permit.get('schema') != 1 or permit.get('password_bypass') is not True
            or permit.get('username') != intent.username or permit.get('character_id') != intent.character_id
            or permit.get('host') != connection.host or permit.get('port') != 26000
            or type(permit.get('account_id')) is not int or permit['account_id'] <= 0
            or not isinstance(permit.get('runtime_id'),str) or len(permit['runtime_id']) != 64):
        raise LANError('Linux не подтвердил выбранный аккаунт и персонажа.')
    capability=inspect_client_auto_login_capability(client)
    if not capability.supported:
        raise LANError('Автологин клиента недоступен: '+capability.reason)
    return build_auto_login_arguments(intent)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise LANError('Перенаправление портретов запрещено.')


def portrait_loader_factory():
    from ..lan import CONFIG_DIR
    from ..workers.portrait_worker import PortraitLoader
    from .runtime.portraits import PortraitProvider
    opener=build_opener(ProxyHandler({}),NoRedirect())
    return partial(PortraitLoader,cache_dir=CONFIG_DIR/'cache/portraits',
                   provider_factory=partial(PortraitProvider,http_open=opener.open))
