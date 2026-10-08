"""LAN control and client launch window; all blocking work stays off the UI thread."""
from __future__ import annotations
import json
from pathlib import Path
import re
import uuid
import threading

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QInputDialog, QMainWindow, QMessageBox,
)

from .lan import CONFIG_DIR, LAN_VERSION, load_settings, save_settings
from .core.lan_api import Client, Connection, LANError
from .core import lan_client
from .core.process_tracker import ProcessTracker
from .lan_presentation import Presentation


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
        self.sync_view()

    def confirm(self, title, message):
        self.timer.stop()
        try:
            return QMessageBox.question(self,title,message)==QMessageBox.StandardButton.Yes
        finally:
            self.timer.start(5000)

    def import_connection(self):
        if self.worker or self.settings.get('pending_job'):return
        self.timer.stop()
        try:name,_=QFileDialog.getOpenFileName(self,'Файл подключения LinuxNative','','JSON (*.json)')
        finally:self.timer.start(5000)
        if not name:return
        try:
            connection=Connection.read(Path(name))
            raw=json.dumps(dict(schema=1,**vars(connection))).encode()
            CONFIG_DIR.mkdir(parents=True,exist_ok=True)
            temporary=CONFIG_DIR/'connection.tmp';temporary.write_bytes(raw);temporary.replace(CONFIG_DIR/'connection.json')
            self.connection=connection;self.last_status=None
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
        def fetch():
            api=Client(connection)
            status=api.status()
            if job:
                try:status['requested_job']=api.job(job)
                except LANError as error:
                    status['job_error']=str(error)
                    status['job_missing']=error.status==404
            return status
        self.run_work(fetch,self.show_status,quiet=True)

    def show_status(self,status):
        self.last_status=status
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
        if self.tracker.is_account_running(profile):
            self.note.setText('Этот профиль уже запущен.');return
        self.persist_client_path()
        path=self.client_path.text().strip();connection=self.connection
        def done(process):
            self.tracker.add(profile, profile, process)
            self.note.setText(f'Клиент запущен: {profile}, PID {process.pid}. Вход в аккаунт — в игре.')
        self.run_work(lambda:lan_client.launch_process(path,profile,connection),done)

    def launch_all(self):
        if not self.connection or self.worker:return
        profiles=[p for p in self.settings['profiles'] if not self.tracker.is_account_running(p)]
        if not profiles:return
        self.persist_client_path()
        path=self.client_path.text().strip();connection=self.connection
        self.cancel_batch.clear();self.batch_active=True
        self._home_page.set_launch_progress(0,len(profiles),0)
        def launch():
            started=[];error=''
            for profile in profiles:
                if self.cancel_batch.is_set():break
                try:started.append((profile,lan_client.launch_process(path,profile,connection)))
                except Exception as exc:
                    error=str(exc);break
            return started,error
        def done(result):
            started,error=result
            for profile,process in started:self.tracker.add(profile,profile,process)
            self.batch_active=False
            self._home_page.finish_launch_progress(len(started),len(started),self.cancel_batch.is_set())
            self.note.setText(f'Запущено профилей: {len(started)} из {len(profiles)}.' + (' '+error if error else ''))
        self.run_work(launch,done)

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
            'Список персонажей, авто-вход и управление модами через API пока недоступны.')

    def closeEvent(self,event):
        if self.worker is not None:
            self.note.setText('Дождитесь завершения текущего запроса перед закрытием.');event.ignore()
        else:
            self.timer.stop()
            event.accept()
