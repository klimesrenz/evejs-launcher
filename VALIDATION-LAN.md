# Проверки LAN Launcher 0.1.1 — восстановление интерфейса

2026-10-08. Основа: launcher lan/11c0a10, платформа 1.0.69, отдельная версия
LAN 0.1.1. LinuxNative0.4.0/API не менялись; оригинальные RPG-контроллеры и
общие виджеты также не менялись. До новой Windows-сборки выполнено:

- 52 существующие проверки config, home actions/layout, nav, theme и process
  tracker прошли в Qt offscreen на Linux.
- Временный интеграционный сценарий нового окна: настоящие HomePage/NavPanel/
  StatusBar, пять страниц, импорт настроек0.1.0, пауза polling в подтверждении,
  UUID и отсутствие повторной команды, единые статусы, журналы, обрыв связи.
- Запуск/завершение/счётчик проверены на настоящих временных Python-процессах:
  повторный запуск профиля блокируется, batch cancel прекращает очередь,
  ошибка второго запуска сохраняет владение первым. Закрытие окна оставляет
  клиент работающим. Это не игровые EVE-процессы; Windows spawn/trust/junction
  в этом сценарии заменены fixture.
- Скриншоты главной и настроек получены через Qt; главный экран просмотрен.
  Для frameless-окна добавлен QSizeGrip. Упаковка обязана включать штатный
  operations_orbital.png, логотип и публичный trust helper.
- Независимое статическое ревью: открытых P1/P2 нет. Неполный перевод LAN
  устранён ограничением интерфейса русским языком в этом выпуске.
- Python syntax и git diff --check прошли. Новых тестов в репозитории нет.

Более широкий прогон обнаружил четыре уже существующих расхождения:
status_bar_layout ожидает версию без RPG-суффикса и ширину1000 (фактически1059
в этой Linux/font-среде), service_status ожидает основной порт26000 вместо
RPG27000. Все четыре воспроизведены в отдельно извлечённом неизменённом
11c0a10. Общие константы/RPG-поведение ради тестов не менялись. Windows-only
home_status импортирует ctypes.windll и не собирается на Linux. Windows build
сохраняет прежний набор config/launcher/profiles и дополняет его пятью
совместимыми UI/process файлами; неизменённые несовместимые suites не включены.

Новая Windows EXE-сборка, native trust/junction, реальный вход EVE и длительная
игра ещё не проверены. Старый успешный Actions37720931120 относится к0.1.0.
Ниже сохранён исторический протокол первой версии.

---

# LinuxNative 0.4.0 / LAN Launcher 0.1.0 — проверка 08.10.2026

Исходники для первого игрового прогона готовы. Windows EXE ещё не собран;
публикация ветки lan для GitHub Actions требует разрешения пользователя.

## Основа

- Основной репозиторий 3deb099c1 / package 0.12.6, launcher c55f05d.
- Реальная Linux-сборка предоставлена пользователем, server/package.json 0.12.9.
- Source archive SHA256: 62ba12aeb4301d5fa19885108985c415a760231d5b7d7a2a556598b3ae48ff3d.
- 19 файлов сверены с collector report; proxy/TLS/chat совпали с rrfarmer/main
  7603a2966 после нормализации CRLF. Server schema из фактического архива.
- 5 сетевых файлов защищены fingerprint в lan-source-policy.json. Серверные
  исходники и файлы модов не патчатся, используется environment при запуске.

## Выполнено

- Синтаксис всех LinuxNative Python, новых launcher Python и common/start-game shell.
- Настоящий TLS handshake между API и Windows transport на Linux loopback;
  отказ неверного token; неверный pin отклоняется до отправки Authorization.
- Повтор UUID без второго выполнения; конфликт UUID/команды, busy, persisted
  result, interrupted после restart, initial journal write failure без выполнения.
- Worker-start failure сохраняет failed и не ломает close. Медленные HTTP
  заголовки прерываются deadline10s; idle TLS не блокирует другие соединения.
- Логи читаются с конца, максимум65536 байт. RFC1918 адреса проверяются отдельно.
- Настоящие временные процессы: start Market→Game, ownership/readiness,
  pending guard, shutdown ждёт operation.lock и посылает SIGINT Game→Market.
  Это Python HTTP fixtures, не настоящий EVE Game/Market.
- Installer prepare/repeat на фактических source files: стабильный token/key,
  bundle без private key, права0600. systemd-analyze verify прошёл для двух units.
  В installer fixture привязка к IP и stopped guard заменены заглушками:
  агентская среда не имеет IP192.168.0.150. Реальные bind/install не выполнялись.
- Qt offscreen: окно, кнопки, вывод состояния, пауза timer во время modal,
  очистка pending неизвестного job без повторной команды, закрытие.
- Настоящие временные клиентские файлы: prepare/repeat, исключение backup
  из CA scan, interrupted restore не повреждает live файл, повторный restore
  возвращает исходные байты. Windows helpers/mutex/trust/resource check были
  изолированы заглушками; это проверка файловой логики, не Windows-приёмка.
- Существующий tests/test_config.py: 17 passed. Windows helper/profile suite
  предусмотрен build-lan.ps1; в Linux напрямую недоступен ctypes.windll.
- Collector на приманках исключает .env/ключи/SQLite/симлинк наружу, не меняет
  исходники и отказывает при существующем выходном архиве.

## Ревью и исправления

Независимые ревью выявили и привели к исправлению: absolute HTTP deadline,
worker-start failure, lock/install и lock/shutdown, ложная инструкция сменыIP,
неатомарный клиентский restore, modal timer race. Верификация systemd выявила
неверные кавычки WorkingDirectory: исправлено, verify затем прошёл.
Финальное независимое интеграционное ревью не выявило подтверждённых P1/P2.
Окно дедупликации — последние100 UUID; старые команды не повторять автоматически.

## Ещё требуется

- Windows build/EXE и запуск на Windows, настоящий CurrentUser trust/junction.
- Первое подключение: Game login, чат, ресурсы/портреты, все UI модов.
- Windows/Linux firewall на конкретных хостах (автоматически не меняются).
- Manjaro install/restart API без остановки мира, orderly shutdown/reboot.
- Несколько клиентов до привычных11, одновременно RPG и длительная игра.
- Причина текущих лагов не диагностировалась этой реализацией.

Сохранённые воспроизводимые сценарии и screenshot:
_local/artifacts/LinuxNative-LAN-development-20261008 (основной checkout).
Подготовка/откат: LAN-README.md. В ZIP отсутствуют credentials, CA/key и мир.
