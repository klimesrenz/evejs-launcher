"""LAN control and client launch window; all blocking work stays off the UI thread."""
from __future__ import annotations
import json
from pathlib import Path
import re
import uuid
import threading
import time

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QInputDialog, QMainWindow, QMessageBox,
)

from .lan import CONFIG_DIR, LAN_VERSION, load_settings, save_settings
from .core.lan_api import Client, Connection, LANError
from .core import lan_client
from .core.process_tracker import ProcessTracker
from .lan_presentation import Presentation
from .core.lan_characters import parse_roster, account_profile
from .core.client_autologin import AutoLoginLaunch
from .core.runtime.portraits import PortraitTarget
from .core.runtime.endpoints import Endpoint


class Worker(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation())
        except Exception as error:
            self.error.emit(str(error))


class Window(Presentation, QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.connection = None
        self.worker = None
        self.last_status = None
        self.tracker = ProcessTracker()
        self.batch_active = False
        self.cancel_batch = threading.Event()
        self.accounts = []
        self.roster_ready = False
        self.login_capability = {'supported': False, 'reason': 'Обновите список персонажей.'}
        self.last_roster_fetch = 0
        self.settings.setdefault('selected_characters', {})
        self.settings.setdefault('hidden_characters', [])
        if not isinstance(self.settings['selected_characters'], dict) or not isinstance(self.settings['hidden_characters'], list):
            raise ValueError('Повреждён сохранённый выбор персонажей LAN.')
        self.build_ui()
        path=CONFIG_DIR/'connection.json'
        if path.exists():
            try:
                self.connection=Connection.read(path);self.address.setText(f'Linux: {self.connection.host}:26080 · HTTPS')
            except Exception as error:
                self.note.setText(str(error))
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000)
        self.sync_view()
        self.refresh()

    def run_work(self, operation, on_success, *, quiet=False):
        if self.worker is not None:
            if not quiet:self.note.setText('Дождитесь завершения текущего запроса.')
            return False
        self.worker=Worker(operation,self)
        self.worker.result.connect(on_success)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.finished)
        self.sync_view()
        self.rebuild_profiles()
        self.worker.start();return True

    def finished(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
        self.sync_view()
        self.rebuild_profiles()

    def failed(self, message):
        self.note.setText(message)
        self.state.setText('Ответ не подтверждён; состояние сервера неизвестно')
        self.last_status = None
        self.roster_ready = False
        self.sync_view()

    def confirm(self, title, message):
        self.timer.stop()
        try:
            return QMessageBox.question(self,title,message)==QMessageBox.StandardButton.Yes
        finally:
            self.timer.start(5000)

    def import_connection(self):
        if self.worker or self.settings.get('pending_job') or self.tracker.running_count:return
        self.timer.stop()
        try:name,_=QFileDialog.getOpenFileName(self,'Файл подключения LinuxNative','','JSON (*.json)')
        finally:self.timer.start(5000)
        if not name:return
        try:
            connection=Connection.read(Path(name))
            raw=json.dumps(dict(schema=1,**vars(connection))).encode()
            CONFIG_DIR.mkdir(parents=True,exist_ok=True)
            temporary=CONFIG_DIR/'connection.tmp';temporary.write_bytes(raw);temporary.replace(CONFIG_DIR/'connection.json')
            old_identity = (self.connection.host, self.connection.certificate_sha256) if self.connection else None
            self.connection=connection;self.last_status=None
            self.last_roster_fetch=0;self.roster_ready=False
            if old_identity != (connection.host, connection.certificate_sha256):
                self.accounts=[]
                self.settings['selected_characters']={}
                self.settings['hidden_characters']=[]
                self._characters_page.invalidate_portrait_target()
                self._characters_page.refresh([],[],self.tracker)
            self.settings['pending_job']='';save_settings(self.settings)
            self.address.setText(f'Linux: {connection.host}:26080 · HTTPS')
            self.refresh()
        except Exception as error:self.failed(str(error))

    def refresh(self):
        if self.tracker.prune_dead():self.rebuild_profiles()
        self.sync_view()
        if not self.connection:return
        connection=self.connection
        job=self.settings.get('pending_job','')
        fetch_roster=time.monotonic()-self.last_roster_fetch>=15
        def fetch():
            api=Client(connection)
            status=api.status()
            if fetch_roster:
                try:status['roster']=api.characters()
                except LANError as error:
                    status['roster_error']='Обновите LinuxNative до 0.5.0 для списка персонажей.' if error.status==404 else str(error)

            if job:
                try:status['requested_job']=api.job(job)
                except LANError as error:
                    status['job_error']=str(error)
                    status['job_missing']=error.status==404
            return status
        self.run_work(fetch,self.show_status,quiet=True)

    def show_status(self,status):
        self.last_status=status
        if 'roster' in status:
            self.last_roster_fetch=time.monotonic()
            try:
                self.accounts,self.login_capability=parse_roster(status['roster'])
                self.roster_ready=True
                target=PortraitTarget(
                    target_identity='lan:'+self.connection.host+':'+self.connection.certificate_sha256,
                    image_endpoint=Endpoint('image',self.connection.host,26001,26001,'tcp'))
                self._characters_page.set_data_error('')
                self._characters_page.refresh(self.accounts,self.settings['hidden_characters'],self.tracker,portrait_target=target)
                self._characters_page.page_header.set_subtitle(
                    'Выбор запоминается для аккаунта; по умолчанию — первый видимый персонаж. Наведите на «Запустить выбранных» для списка.'
                    if self.login_capability['supported'] else self.login_capability['reason']+' Ручной вход — в Настройках.')
            except LANError as error:
                self.roster_ready=False
                self._characters_page.set_data_error(str(error))
        elif 'roster_error' in status:
            self.last_roster_fetch=time.monotonic();self.roster_ready=False
            self._characters_page.set_data_error(status['roster_error'])
        names={'running':'работает','stopped':'остановлен','starting':'запускается','external':'внешний процесс','stale':'остались дочерние процессы'}
        self.state.setText(' · '.join(name.upper()+': '+names.get(value['state'],value['state']) for name,value in status['services'].items()))
        job=status.get('requested_job') or status.get('jobs',{}).get('active')
        if job:
            if job['state']=='succeeded':
                self.note.setText('Операция завершена: '+job['action'])
                self.settings['pending_job']='';save_settings(self.settings)
            elif job['state'] in ('failed','interrupted'):
                self.note.setText(job.get('error','Операция не завершена.'))
                self.settings['pending_job']='';save_settings(self.settings)
            else:self.note.setText('Выполняется: '+job['action'])
        elif status.get('job_error'):
            self.note.setText(status['job_error'])
        if status.get('job_missing'):
            self.settings['pending_job']='';save_settings(self.settings)
            self.note.setText('Запрос не найден. Проверьте показанное состояние служб; команда автоматически не повторяется.')
        if status.get('pending'):self.note.setText('На Linux есть незавершённая операция модов. Откройте manage.sh → восстановление.')
        self.sync_view()

    def action(self, action):
        if self.worker or not self.connection:return
        if self.settings.get('pending_job'):
            self.note.setText('Сначала дождитесь результата предыдущей операции или обновите статус.');return
        if action in ('stop','stop-game') and not self.confirm('Остановка','Штатно выполнить '+action+'? Клиенты Game будут отключены.'):return
        identity=str(uuid.uuid4());self.settings['pending_job']=identity;save_settings(self.settings)
        connection=self.connection
        def send():
            try:return Client(connection).action(action,identity)
            except LANError as error:
                if error.status in (400,401,403,404,409,413,415):return {'rejected':str(error)}
                raise
        def done(result):
            if 'rejected' in result:
                self.settings['pending_job']='';save_settings(self.settings);self.note.setText(result['rejected'])
            else:self.note.setText('Команда принята: '+result['action'])
        self.run_work(send,done)

    def logs(self,name):
        if self.connection:self.run_work(lambda:Client(self.connection).logs(name),lambda result:self.log.setPlainText(result['text']))

    def persist_client_path(self):
        self.settings['client_path']=self.client_path.text().strip();save_settings(self.settings)

    def browse_client(self):
        self.timer.stop()
        try:path=QFileDialog.getExistingDirectory(self,'Папка tq основного клиента',self.client_path.text())
        finally:self.timer.start(5000)
        if path:self.client_path.setText(path);self.persist_client_path()

    def add_profile(self):
        self.timer.stop()
        try:value,ok=QInputDialog.getText(self,'Новый профиль','Имя (английские буквы, цифры, _ и -):')
        finally:self.timer.start(5000)
        if not ok:return
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',value):self.note.setText('Недопустимое имя профиля.');return
        if value.casefold() in {x.casefold() for x in self.settings['profiles']}:return
        self.settings['profiles'].append(value);save_settings(self.settings);self.profiles.addItem(value);self.profiles.setCurrentText(value)
        self.rebuild_profiles()

    def prepare_client(self):
        if not self.connection or self.worker:return
        if not self.confirm('Подготовка LAN-клиента','Закройте все EVE-клиенты. Изменить адрес в start.ini, добавить публичный игровой CA в клиент и Windows CurrentUser trust? Исходные файлы будут сохранены.'):return
        path=self.client_path.text().strip();connection=self.connection
        self.run_work(lambda:lan_client.prepare(path,connection),self.note.setText)

    def restore_client(self):
        if self.worker:return
        if not self.confirm('Откат клиента','Закройте все EVE-клиенты. Восстановить файлы из LAN-backup?'):return
        path=self.client_path.text().strip();self.run_work(lambda:lan_client.restore(path),self.note.setText)

    def toggle_game(self):
        running = (self.last_status or {}).get('services', {}).get('game', {}).get('state') == 'running'
        self.action('stop-game' if running else 'start')

    def launch_client(self):
        self.launch_profile(self.profiles.currentText())

    def launch_profile(self, profile):
        if not self.connection or self.worker:return
        if self.tracker.is_account_running('profile:'+profile):
            self.note.setText('Этот профиль уже запущен.');return
        self.persist_client_path()
        path=self.client_path.text().strip();connection=self.connection
        def done(process):
            self.tracker.add('profile:'+profile, profile, process)
            self.note.setText(f'Клиент запущен: {profile}, PID {process.pid}. Вход в аккаунт — в игре.')
        self.run_work(lambda:lan_client.launch_process(path,profile,connection),done)

    def refresh_characters(self):
        self.last_roster_fetch=0
        self.refresh()

    def selected_launches(self):
        selected=self.settings.get('selected_characters',{})
        hidden=set(self.settings.get('hidden_characters',[]))
        result=[]
        for account in self.accounts:
            if account.banned or self.tracker.is_account_running(account.username):continue
            choices=[c for c in account.characters if c.name not in hidden]
            if not choices:continue
            character=next((c for c in choices if c.char_id==selected.get(account.username)),choices[0])
            result.append((account.username,character.name,character.char_id,account.account_id))
        return result

    def select_character(self,username,name,character_id):
        self.settings['selected_characters'][username]=character_id
        save_settings(self.settings)
        self.note.setText(f'Для аккаунта {username} выбран {name}. Общий запуск использует этот выбор.')
        self.sync_view()

    def launch_character(self,username,name,character_id):
        if self.worker or not self.connection:return
        if not self.roster_ready or not self.login_capability.get('supported'):
            self.note.setText(self.login_capability.get('reason','Обновите список.'));return
        if self.tracker.is_account_running(username):
            self.note.setText('Клиент этого аккаунта уже запущен.');return
        found=next(((a,c) for a in self.accounts if a.username==username and not a.banned
                    for c in a.characters if c.char_id==character_id),None)
        if not found:
            self.note.setText('Персонаж отсутствует в актуальном списке. Обновите список.');return
        account,character=found
        self.select_character(username,character.name,character_id)
        self.launch_character_batch([(username,character.name,character_id,account.account_id)])

    def launch_all(self):
        if self.worker or not self.connection or not self.roster_ready or not self.login_capability.get('supported'):return
        self.launch_character_batch(self.selected_launches())

    def launch_character_batch(self,characters):
        if not characters:return
        self.persist_client_path()
        path=self.client_path.text().strip();connection=self.connection
        self.cancel_batch.clear();self.batch_active=True
        for username,name,_,_ in characters:self._characters_page.set_account_launching(username,name,True)
        self._home_page.set_launch_progress(0,len(characters),0)
        self._characters_page.set_group_launch_progress(0,len(characters),0)
        def launch():
            started=[];error=''
            for username,name,identity,account_id in characters:
                if self.cancel_batch.is_set():break
                try:
                    profile=account_profile(connection,account_id)
                    process=lan_client.launch_process(path,profile,connection,intent=AutoLoginLaunch(username,identity))
                    started.append((username,name,process))
                except Exception as exc:
                    error=str(exc);break
            return started,error
        def done(result):
            started,error=result
            for username,name,process in started:self.tracker.add(username,name,process)
            for username,name,_,_ in characters:self._characters_page.set_account_launching(username,name,False)
            self.batch_active=False
            self._home_page.finish_launch_progress(len(started),len(started),self.cancel_batch.is_set())
            self._characters_page.finish_group_launch_progress()
            self.note.setText(f'Запущено клиентов: {len(started)} из {len(characters)}.' + (' '+error if error else ''))
        self.run_work(launch,done)

    def hide_character(self,name):
        if name not in self.settings['hidden_characters']:
            self.settings['hidden_characters'].append(name);save_settings(self.settings)
        self._characters_page.refresh(self.accounts,self.settings['hidden_characters'],self.tracker,
                                      portrait_target=self._characters_page._portrait_target)
        self.sync_view()

    def unhide_characters(self):
        self.settings['hidden_characters']=[];save_settings(self.settings)
        self._characters_page.refresh(self.accounts,[],self.tracker,portrait_target=self._characters_page._portrait_target)
        self.sync_view()

    def unavailable_roster_action(self,*args):
        self.note.setText('Создание, удаление и группы не входят в LAN-управление. Выбор и запуск доступны на карточке.')

    def cancel_launches(self):
        self.cancel_batch.set()
        self.note.setText('Оставшиеся профили не будут запущены; текущий запуск завершается.')

    def kill_clients(self):
        if self.worker or not self.tracker.running_count:return
        if not self.confirm('Закрыть клиенты','Завершить только клиенты, запущенные этим окном LAN-лаунчера?'):return
        self.note.setText(f'Отправлено команд завершения: {self.tracker.kill_all()}.')
        self.tracker.prune_dead();self.sync_view();self.rebuild_profiles()

    def show_release_notes(self):
        QMessageBox.information(self,'LAN '+LAN_VERSION,
            'Возвращены оформление, навигация и главная страница исходного лаунчера.\n'
            'Управление Linux, журналы, клиентские профили и подготовка доступны через LAN.\n'
            'Доступны карточки персонажей Linux, штатный вход и очередь запуска аккаунтов.\n'
            'Управление модами выполняется через LinuxNative.')

    def closeEvent(self,event):
        if self.worker is not None:
            self.note.setText('Дождитесь завершения текущего запроса перед закрытием.');event.ignore()
        elif self._characters_page.portrait_loads_active():
            self.timer.stop()
            self._characters_page.cancel_portrait_loads()
            self.note.setText('Завершается загрузка портретов…')
            event.ignore()
            QTimer.singleShot(100,self.close)
        else:
            self.timer.stop()
            event.accept()
