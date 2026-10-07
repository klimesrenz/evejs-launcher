# Проверка RPG Launcher 0.1.0 — 2026-10-07

Основа: upstream 1.0.69 / fdde2ddf80a11237ad0cbd7955ee493d90ff6158.

Выполнено локально:

- Python compileall для src, main.py и scripts/package-rpg.py — успешно.
- git diff --check — успешно.
- Существующие tests/test_config.py и tests/test_update_asset_selection.py:
  upstream — 23 passed; RPG — 23 passed. Qt offscreen, отдельный APPDATA.
- Отдельная проверка значений APP_NAME/CONFIG_DIR, Game/Proxy/Market,
  updater repo и выключенной по умолчанию автопроверки — успешно.
- Проверка очищенного окружения с подставленными чужими EVEJS_DATA_ROOT,
  EVEJS_GAMESTORE_DATA_DIR, NODE_OPTIONS, NODE_PATH и CDN 443 — успешно;
  нужные PATH/APPDATA сохранены, исходный словарь не изменён.
- scripts/build-rpg.ps1 разобран PowerShell Parser на Windows пользователя
  по SSH, без выполнения сборки — ошибок синтаксиса нет.

Не выполнено:

- Windows-зависимые pytest-наборы из scripts/build-rpg.ps1.
- Сборка и упаковка EXE через PyInstaller.
- Запуск упакованного UI, управление реальными службами и вход в RPG-клиент.
- Обновление установленного RPG Launcher из собственного GitHub Release.

Эти результаты не являются полной игровой приёмкой. Workflow собирает
пакет только после прохождения выбранных Windows-проверок; затем пользователь
проверяет запуск по RPG.md. Публикация ветки и запуск workflow пока ожидают
разрешения пользователя на git push. Новые тесты не добавлены.
