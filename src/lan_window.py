"""LAN control and client launch window; all blocking work stays off the UI thread."""
from __future__ import annotations
import json
from pathlib import Path
import re
import uuid

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QVBoxLayout, QWidget)

from .lan import CONFIG_DIR, LAN_VERSION, VERSION, load_settings, save_settings
from .core.lan_api import Client, Connection, LANError
from .core import lan_client


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


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'EVE.js LAN Launcher {LAN_VERSION} — API {VERSION}')
        self.resize(900, 650)
        self.settings = load_settings()
        self.connection = None
        self.worker = None
        self.current_action = None
        self.last_status = None
        central = QWidget();self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        header = QLabel('ОСНОВНОЙ СЕРВЕР · LINUX LAN')
        header.setStyleSheet('font-size:22px; font-weight:600; color:#63d5bf; padding:12px 0;')
        layout.addWidget(header)
        self.address = QLabel('Импортируйте файл подключения, созданный на Linux.')
        layout.addWidget(self.address)
        buttons = QHBoxLayout();layout.addLayout(buttons)
        for text, callback in (('Импорт подключения',self.import_connection),('Обновить статус',self.refresh)):
            button=QPushButton(text);button.clicked.connect(callback);buttons.addWidget(button)
        self.state = QLabel('Состояние сервера неизвестно');layout.addWidget(self.state)
        controls = QHBoxLayout();layout.addLayout(controls)
        self.controls=[]
        for text,action in (('Запустить сервер','start'),('Остановить сервер','stop'),('Остановить Game','stop-game'),('Запустить Game','start-game')):
            button=QPushButton(text);button.clicked.connect(lambda _,a=action:self.action(a));controls.addWidget(button);self.controls.append(button)
        self.note = QLabel('Закрытие лаунчера оставляет сервер работающим.');self.note.setWordWrap(True);layout.addWidget(self.note)
        tabs=QTabWidget();layout.addWidget(tabs)
        client_tab=QWidget();client_layout=QVBoxLayout(client_tab);tabs.addTab(client_tab,'Клиенты')
        row=QHBoxLayout();client_layout.addLayout(row)
        self.client_path=QLineEdit(str(self.settings.get('client_path','')));self.client_path.setPlaceholderText('Папка tq основного offline-клиента')
        row.addWidget(self.client_path);browse=QPushButton('Выбрать tq');browse.clicked.connect(self.browse_client);row.addWidget(browse)
        self.client_path.editingFinished.connect(self.persist_client_path)
        row=QHBoxLayout();client_layout.addLayout(row)
        prep=QPushButton('Подготовить LAN-клиент');prep.clicked.connect(self.prepare_client);row.addWidget(prep)
        undo=QPushButton('Откатить подготовку');undo.clicked.connect(self.restore_client);row.addWidget(undo)
        row=QHBoxLayout();client_layout.addLayout(row)
        self.profiles=QComboBox();self.profiles.addItems(self.settings.get('profiles',['Main']));row.addWidget(self.profiles)
        add=QPushButton('Добавить профиль');add.clicked.connect(self.add_profile);row.addWidget(add)
        launch=QPushButton('Запустить клиент');launch.clicked.connect(self.launch_client);row.addWidget(launch)
        description=QLabel('Каждый профиль имеет отдельные настройки EVE. Вход в аккаунт — в окне игры.\n'
            'Моды загружает LinuxNative из существующего профиля. AutoMining сохраняет игровые настройки;\n'
            'локальные настройки профилей старого Windows-лаунчера автоматически не переносятся.')
        description.setWordWrap(True);client_layout.addWidget(description);client_layout.addStretch()
        log_tab=QWidget();log_layout=QVBoxLayout(log_tab);tabs.addTab(log_tab,'Журналы сервера')
        row=QHBoxLayout();log_layout.addLayout(row)
        for name in ('game','market'):
            button=QPushButton('Обновить '+name);button.clicked.connect(lambda _,n=name:self.logs(n));row.addWidget(button)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);log_layout.addWidget(self.log)
        self.setStyleSheet('QWidget {background:#101b27;color:#e4edf5;font-size:13px;} '
            'QPushButton {background:#23364a;padding:9px;border:1px solid #3b536b;border-radius:4px;} '
            'QPushButton:disabled {color:#66798b;} QLineEdit,QComboBox,QPlainTextEdit {background:#0b141f;padding:8px;}')
        path=CONFIG_DIR/'connection.json'
        if path.exists():
            try:
                self.connection=Connection.read(path);self.address.setText(f'Linux: {self.connection.host}:26080 · HTTPS')
            except Exception as error:
                self.note.setText(str(error))
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000)
        for button in self.controls:button.setEnabled(self.connection is not None)
        self.refresh()

    def run_work(self, operation, on_success, *, quiet=False):
        if self.worker is not None:
            if not quiet:self.note.setText('Дождитесь завершения текущего запроса.')
            return False
        self.worker=Worker(operation,self)
        self.worker.result.connect(on_success)
        self.worker.error.connect(self.failed)
        self.worker.finished.connect(self.finished)
        for button in self.controls:button.setEnabled(False)
        self.worker.start();return True

    def finished(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
        for button in self.controls:button.setEnabled(self.connection is not None)

    def failed(self, message):
        self.note.setText(message)
        self.state.setText('Ответ не подтверждён; состояние сервера неизвестно')

    def confirm(self, title, message):
        self.timer.stop()
        try:
            return QMessageBox.question(self,title,message)==QMessageBox.StandardButton.Yes
        finally:
            self.timer.start(5000)

    def import_connection(self):
        if self.worker:return
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
        path=QFileDialog.getExistingDirectory(self,'Папка tq основного клиента',self.client_path.text())
        if path:self.client_path.setText(path);self.persist_client_path()

    def add_profile(self):
        value,ok=QInputDialog.getText(self,'Новый профиль','Имя (английские буквы, цифры, _ и -):')
        if not ok:return
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',value):self.note.setText('Недопустимое имя профиля.');return
        if value.casefold() in {x.casefold() for x in self.settings['profiles']}:return
        self.settings['profiles'].append(value);save_settings(self.settings);self.profiles.addItem(value);self.profiles.setCurrentText(value)

    def prepare_client(self):
        if not self.connection or self.worker:return
        if not self.confirm('Подготовка LAN-клиента','Закройте все EVE-клиенты. Изменить адрес в start.ini, добавить публичный игровой CA в клиент и Windows CurrentUser trust? Исходные файлы будут сохранены.'):return
        path=self.client_path.text().strip();connection=self.connection
        self.run_work(lambda:lan_client.prepare(path,connection),self.note.setText)

    def restore_client(self):
        if self.worker:return
        if not self.confirm('Откат клиента','Закройте все EVE-клиенты. Восстановить файлы из LAN-backup?'):return
        path=self.client_path.text().strip();self.run_work(lambda:lan_client.restore(path),self.note.setText)

    def launch_client(self):
        if not self.connection:return
        path=self.client_path.text().strip();profile=self.profiles.currentText();connection=self.connection
        self.run_work(lambda:lan_client.launch(path,profile,connection),self.note.setText)

    def closeEvent(self,event):
        if self.worker is not None:
            self.note.setText('Дождитесь завершения текущего запроса перед закрытием.');event.ignore()
        else:event.accept()
