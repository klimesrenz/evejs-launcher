"""Original launcher shell with Linux LAN actions and isolated settings.

Reuse the upstream presentation widgets, never its local-server controllers.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSizeGrip, QStackedWidget, QVBoxLayout, QWidget,
)
from . import theme
from .constants import Page
from .core.service_status import RuntimeSnapshot, ServiceState
from .i18n import set_language
from .lan import LAN_VERSION, VERSION
from .pages.home_page import HomePage
from .widgets.nav_panel import NavPanel
from .widgets.page_header import PageHeader
from .widgets.status_bar import StatusBar
from .widgets.title_bar import TitleBar


class Presentation:
    def build_ui(self):
        set_language('ru')
        self.setWindowTitle(f'EVE.js Launcher — LAN {LAN_VERSION}')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1100, 720)
        self.resize(1400, 860)
        self.setStyleSheet(theme.build_qss(theme.load_fonts()))
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._title_bar = TitleBar(self)
        self._title_bar.set_title(f'EVE.js Launcher — LAN {LAN_VERSION}')
        # The LAN release has no published updater feed or audio controller.
        self._title_bar.update_btn.setEnabled(False)
        self._title_bar.update_btn.setToolTip('Обновление LAN-пакета — заменой папки лаунчера.')
        self._title_bar.audio_capsule.setEnabled(False)
        self._title_bar.audio_capsule.setToolTip('Звуковое сопровождение пока недоступно в LAN-версии.')
        root.addWidget(self._title_bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._nav = NavPanel(self)
        body.addWidget(self._nav)
        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)
        root.addLayout(body, 1)
        self._home_page = HomePage()
        self._stack.addWidget(self._home_page)
        self._build_profiles_page()
        self._build_mods_page()
        self._build_tools_page()
        self._build_settings_page()
        self.note = QLabel('Подключение к Linux задаётся в настройках. Закрытие окна оставляет сервер работающим.')
        self.note.setWordWrap(True)
        self.note.setContentsMargins(16, 8, 16, 8)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.note)
        self._status_bar = StatusBar(self)
        self._status_bar.version_label.setText(f'{VERSION} (LAN {LAN_VERSION})')
        root.addWidget(self._status_bar)
        self._status_bar.layout().addWidget(QSizeGrip(self))
        self._status_bar.language_combo.setEnabled(False)
        self._status_bar.language_combo.setToolTip('LAN-интерфейс этого выпуска доступен на русском языке.')
        self._status_bar.console_toggled.connect(self.open_logs)
        self._nav.page_changed.connect(self.switch_page)
        self._nav.server_toggled.connect(self.toggle_game)
        self._nav.market_toggled.connect(lambda: self.open_logs('market'))
        self._nav.kill_all_clicked.connect(self.kill_clients)
        self._home_page.start_servers_clicked.connect(lambda: self.action('start'))
        self._home_page.stop_servers_clicked.connect(lambda: self.action('stop'))
        self._home_page.launch_all_clicked.connect(self.launch_all)
        self._home_page.cancel_launches_clicked.connect(self.cancel_launches)
        self._home_page.kill_all_clicked.connect(self.kill_clients)
        self._home_page.console_requested.connect(self.open_logs)
        # Profiles are independent client installations, not server character groups.
        self._home_page.group_combo.hide()
        self._home_page.btn_changelog.clicked.disconnect()
        self._home_page.btn_changelog.clicked.connect(self.show_release_notes)
        self.controls = [self._nav.btn_server, self._home_page.btn_start_servers,
                         self.start_button, self.stop_button, self.game_start_button,
                         self.game_stop_button]
        self.switch_page(int(Page.HOME))
        self.sync_view()

    def page(self, title, subtitle):
        page = QWidget()
        page.setProperty('deepSignal', True)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)
        header = PageHeader(title, subtitle, 'DEEP SIGNAL // LINUX LAN')
        outer.addWidget(header)
        self._stack.addWidget(page)
        return page, outer

    @staticmethod
    def button(text, callback, layout, *, primary=False):
        button = QPushButton(text)
        button.setMinimumHeight(40)
        button.setProperty('class', 'primary' if primary else 'secondary')
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def paragraph(text, layout):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty('class', 'pageSubtitle')
        layout.addWidget(label)
        return label

    def _build_profiles_page(self):
        self._characters_page, layout = self.page(
            'Персонажи', 'Профили основного клиента. Вход в аккаунт выполняется в игре.')
        self.paragraph('Список персонажей Linux пока не передаётся через API. '
                       'Здесь показаны ваши клиентские профили; данные мира остаются на сервере.', layout)
        row = QHBoxLayout()
        self.profiles = QComboBox()
        self.profiles.addItems(self.settings.get('profiles', ['Main']))
        row.addWidget(self.profiles, 1)
        self.button('Добавить профиль', self.add_profile, row)
        self.profile_launch = self.button('Запустить клиент', self.launch_client, row, primary=True)
        layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.profile_grid = QGridLayout(holder)
        self.profile_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        self.rebuild_profiles()

    def rebuild_profiles(self):
        while self.profile_grid.count():
            widget = self.profile_grid.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        for index, profile in enumerate(self.settings['profiles']):
            card = QFrame()
            card.setProperty('class', 'card')
            box = QVBoxLayout(card)
            box.setContentsMargins(20, 20, 20, 20)
            title = QLabel(profile)
            title.setProperty('class', 'sectionTitle')
            box.addWidget(title)
            running = self.tracker.is_account_running(profile)
            self.paragraph('Клиент запущен' if running else 'Готов к запуску', box)
            self.button('Запустить', lambda _, p=profile: self.launch_profile(p), box,
                        primary=True).setEnabled(not running and self.worker is None and self.connection is not None)
            self.profile_grid.addWidget(card, index // 3, index % 3)

    def _build_mods_page(self):
        self._mods_page, layout = self.page('Моды', 'Моды основного мира загружает LinuxNative.')
        self.paragraph('Удалённое управление модами пока не поддерживается. '
                       'Установка, обновление и включение выполняются на Linux через существующий менеджер.', layout)
        command = QLineEdit('bash tools/LinuxNative/manage.sh')
        command.setReadOnly(True)
        layout.addWidget(command)
        self.paragraph('Откройте терминал в /home/erooku/EveJS-12.19-linux. '
                       'Настройки и данные установленных модов сохраняются на Linux.', layout)
        self.button('Открыть журнал Game', lambda: self.open_logs('game'), layout)
        layout.addStretch()

    def _build_tools_page(self):
        self._tools_page, layout = self.page('Инструменты', 'Управление службами и журналы Linux.')
        row = QHBoxLayout()
        self.start_button = self.button('Запустить сервер', lambda: self.action('start'), row)
        self.stop_button = self.button('Остановить сервер', lambda: self.action('stop'), row)
        self.game_start_button = self.button('Запустить Game', lambda: self.action('start-game'), row)
        self.game_stop_button = self.button('Остановить Game', lambda: self.action('stop-game'), row)
        layout.addLayout(row)
        self.paragraph('Запуск: Market → Game. Остановка: Game → Market. '
                       'При закрытии лаунчера сервер продолжает работу.', layout)
        row = QHBoxLayout()
        self.log_choice = QComboBox()
        self.log_choice.addItems(['Game', 'Market'])
        row.addWidget(self.log_choice)
        self.button('Обновить журнал', lambda: self.logs(self.log_choice.currentText().lower()), row)
        self.button('Обновить статус', self.refresh, row)
        layout.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

    def _build_settings_page(self):
        self._settings_page, layout = self.page('Настройки', 'Подключение к основному серверу Linux и локальный клиент.')
        self.address = self.paragraph('Импортируйте файл подключения, созданный на Linux.', layout)
        row = QHBoxLayout()
        self.import_button = self.button('Импорт подключения', self.import_connection, row)
        self.button('Проверить подключение', self.refresh, row)
        layout.addLayout(row)
        self.state = self.paragraph('Состояние сервера неизвестно', layout)
        self.paragraph('Папка tq основного offline-клиента 3396210', layout)
        row = QHBoxLayout()
        self.client_path = QLineEdit(str(self.settings.get('client_path', '')))
        self.client_path.setPlaceholderText('Выберите папку tq основного клиента')
        self.client_path.editingFinished.connect(self.persist_client_path)
        row.addWidget(self.client_path, 1)
        self.button('Выбрать tq', self.browse_client, row)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.prepare_button = self.button('Подготовить LAN-клиент', self.prepare_client, row)
        self.restore_button = self.button('Откатить подготовку', self.restore_client, row)
        layout.addLayout(row)
        self.paragraph('Перед подготовкой закройте все EVE-клиенты. Выбирайте основной клиент, '
                       'а не Sandbox RPG. Файлы до подготовки сохраняются для отката.', layout)
        self.paragraph('Профили и настройки: %APPDATA%\\EveJS-LAN-Launcher. '
                       'Сохранённые настройки версии 0.1.0 подхватываются автоматически.', layout)
        layout.addStretch()

    def switch_page(self, index):
        self._stack.setCurrentIndex(index)
        self._nav.set_active_page(index)

    def open_logs(self, name):
        if name == 'clients':
            self.switch_page(int(Page.CHARACTERS))
            return
        name = 'market' if name == 'market' else 'game'
        self.log_choice.setCurrentText(name.capitalize())
        self.switch_page(int(Page.TOOLS))
        self.logs(name)

    def sync_view(self):
        services = (self.last_status or {}).get('services', {})
        mapping = {'running': ServiceState.ONLINE, 'stopped': ServiceState.OFFLINE,
                   'starting': ServiceState.STARTING, 'stale': ServiceState.FAILED}
        game = services.get('game', {})
        market = services.get('market', {})
        snapshot = RuntimeSnapshot(
            game=mapping.get(game.get('state'), ServiceState.UNKNOWN),
            market=mapping.get(market.get('state'), ServiceState.UNKNOWN),
            running_clients=self.tracker.running_count,
            game_pid=game.get('pid'), market_pid=market.get('pid'),
            game_owned=game.get('state') == 'running', market_owned=market.get('state') == 'running')
        self._home_page.apply_runtime_snapshot(snapshot)
        self._home_page.set_server_mode('Linux LAN' + (f' · {self.connection.host}' if self.connection else ''))
        self._status_bar.server_section.set_state(snapshot.game, pid=snapshot.game_pid)
        self._status_bar.market_section.set_state(snapshot.market, pid=snapshot.market_pid)
        self._status_bar.clients_section.set_count(snapshot.running_clients)
        busy = self.worker is not None
        pending = bool(self.settings.get('pending_job')) or bool((self.last_status or {}).get('jobs', {}).get('active'))
        enabled = bool(self.connection) and not busy and not pending
        for button in self.controls:
            button.setEnabled(enabled)
        running = game.get('state') == 'running'
        self._nav.set_service_action_text('server', 'Stop Server' if running else 'Start Server')
        self._nav.set_service_action_text('market', 'Market')
        self._nav.btn_market.setToolTip('Журнал Market; запуск и остановка — вместе с сервером.')
        self._nav.btn_market.setEnabled(bool(self.connection) and not busy)
        self._home_page.btn_start_servers.setText('Остановить сервер' if running or market.get('state') == 'running' else 'Запустить сервер')
        self._home_page._stack_action = 'stop' if running or market.get('state') == 'running' else 'start'
        if not self.connection:
            self._home_page.overall_status_label.setText('НЕТ ПОДКЛЮЧЕНИЯ')
            self._home_page.overall_detail_label.setText('Импортируйте файл подключения в настройках.')
        available = enabled and running
        ready = sum(not self.tracker.is_account_running(p) for p in self.settings['profiles'])
        self._home_page.set_launch_available(available and ready > 0, 'Сначала подключитесь и запустите сервер.', ready_count=ready)
        if not self.batch_active:
            self._home_page.btn_launch_all.setText('Запустить профили')
        self.profile_launch.setEnabled(available)
        for button in (self._nav.btn_kill_all, self._home_page.btn_kill_all):
            button.setEnabled(snapshot.running_clients > 0 and not busy)
            button.setToolTip('Закрыть только клиенты, запущенные этим окном LAN-лаунчера.')
        self._nav.set_badge_count(int(Page.CHARACTERS), snapshot.running_clients)
        self.import_button.setEnabled(not busy and not pending)
        self.prepare_button.setEnabled(bool(self.connection) and not busy)
        self.restore_button.setEnabled(not busy)
