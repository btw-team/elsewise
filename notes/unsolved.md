# Нерешённые вопросы и оставшиеся проблемы

Срез актуален на 2026-08-21 для commit `706a8af`. Автоматический gate `make check`
проходит полностью: форматирование, lint, typecheck, документация, unit/integration
tests, production builds, wheel и synthetic extension E2E. Ниже перечислено то, что
автоматическими проверками пока не закрыто.

## 1. Live-проверка browser adapters

Пользовательский source-run smoke подтверждён на Pop!_OS 22.04 и macOS через
`uv run elsewise-gui`: launcher и server запускались корректно, статусы
отображались, реальные встречи записывались, Chrome и Firefox передавали captions в
Web GUI, а Codex корректно обрабатывал контекст. Обнаруженные при проверке дефекты
Teams и Zoom были исправлены; базовый реальный сценарий для Meet/Teams/Zoom сейчас
работает.

Остаются узкие проверки, не подтверждённые этим отчётом:

- Corporate Teams DOM, `teams.microsoft.com` и региональные поддомены не выделены в
  отдельный smoke; любое найденное отличие следует сохранить как обезличенный fixture.
- Для Zoom всё ещё нужен целевой сценарий captions off/on и смены Speaker/Gallery
  layout непосредственно во время обновления активной реплики.
- Нужен повтор того же browser smoke на установленных release packages; source-run
  проверка не подтверждает manifests/assets/path resolution внутри пакетов.
- Zoom получает display name из приватных полей React (`__reactProps$` /
  `__reactFiber$`). При их изменении захват текста продолжит работать с неизвестным
  speaker, но восстановление имени может сломаться. Этот путь требует отдельной
  live-проверки при каждом изменении Zoom adapter.

Подробные правила для fixtures находятся в
[документации adapters](../docs/development/extension-adapters.md).

## 2. Нативная проверка и release readiness

- Большая часть [platform validation matrix](../docs/testing/platform-validation-matrix.md)
  остаётся в состоянии `NOT RUN`. Есть частичный Linux frozen CLI smoke от 2026-08-19,
  пользовательский source-run smoke на Pop!_OS 22.04/macOS и изолированные Linux
  source checks lifecycle/locking/signals от 2026-08-21. Они подтверждают основные
  GUI, server, browser capture, Codex и process-control flows в исходном окружении, но
  не установочные пакеты и platform-native release cases.
- До публичного релиза нужно проверить реальные артефакты на Windows x64, macOS
  Apple Silicon/Intel и Linux: process lifecycle, locks, high DPI, native dialogs,
  notifications, log rotation, install/update/uninstall и браузерную интеграцию.
- Для Windows необходимо явно зафиксировать поддерживаемые версии ОС. Для macOS нужно
  подтвердить обе архитектуры либо отказаться от непроверенного Intel-артефакта.
- RPM release заблокирован отсутствием выбранного и проверенного Fedora/RHEL-
  совместимого baseline. Сборка RPM в CI сама по себе этот вопрос не решает.
- Первый tagged release workflow ещё не дал зафиксированных checksums, job URLs и
  install-from-release smoke evidence. Эти данные должны быть внесены в platform
  matrix по [release checklist](../docs/release-checklist.md).

## 3. Реальные AgentProvider smoke tests

- Основной Codex flow подтверждён реальными встречами на Pop!_OS 22.04 и macOS.
  Обычный `make check` при этом намеренно пропускает authenticated Codex и Claude Code
  smoke tests. Перед релизом остаётся запустить формальный opt-in suite на минимально
  поддерживаемых версиях CLI и проверить create/resume, streaming, cancel, timeout и
  четыре комбинации write/network permissions. Реальный Claude smoke пока не заявлен.
- Codex model catalog обнаруживается динамически, а Claude model/effort catalog
  частично задан в коде. Изменения CLI могут сделать сохранённый выбор неподдерживаемым;
  совместимость с минимальными версиями CLI пока не зафиксирована отдельной матрицей.

## 4. Распространение

- Preview-артефакты не подписаны: Windows показывает unknown publisher, macOS -
  Gatekeeper warning. Для alpha это осознанное ограничение, но не состояние готового
  доверенного релиза.
- Публичных Chrome Web Store и Firefox AMO listings пока нет. Релизы используют ZIP,
  Chrome `Load unpacked` и временную установку Firefox; ссылки в shared manifest ведут
  на главные страницы магазинов, а не на Elsewise.

## 5. Документация

- В README оставлен видимый placeholder вместо истории создания проекта. Перед
  публичным релизом его нужно заменить авторским текстом или удалить раздел целиком.

## Не считать нерешённым

Следующие пункты из старых notes уже реализованы и покрыты тестами: bounded global
snapshot и paginated session detail, применение простых WebSocket deltas, retention
diagnostics/tombstones/UI events и VACUUM, SQL-выборка agent context, восстановление
повреждённых settings из backup, hot replacement idle agent executable, inactivity и
total turn timeouts, extension dead letters, стабильные локализованные API errors,
modal focus trap/inert background, lazy-loaded Web GUI chunks и переход тестов на
`httpx2`.
