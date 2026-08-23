# Идеи развития и оптимизации

Это рабочий backlog, а не roadmap. Перед реализацией пункту нужны отдельная задача,
acceptance criteria и, где применимо, security/privacy review. Более подробные уже
согласованные заготовки находятся в
[Suggested features](../docs/development/suggested-features.md).

## Ближайшие улучшения

### Диагностика и обслуживание

- Добавить **Export diagnostics**: ограниченный локальный архив с версией, schema
  revision, platform/runtime status, хвостами логов и состоянием providers/extension.
  Перед сохранением показывать точный состав; исключать transcripts, prompts, agent
  output, credentials, pairing/control tokens и environment dumps.
- Добавить в Launcher support-раздел: открыть data/config directories, SQLite
  `integrity_check`, безопасный online backup, восстановление из выбранной копии,
  отображение размера БД и копирование redacted status report.
- Добавить пользовательскую retention-политику для завершённых sessions: напоминание
  о старых данных, export-before-delete и опциональное автоудаление. Сейчас служебные
  события очищаются, но сохранённые transcripts остаются до ручного удаления session.

### Supply-chain и совместимость toolchain

- Зафиксировать GitHub Actions на проверенные immutable commit SHA и документировать
  процедуру обновления pin-ов.
- Добавить узкий project-level allowlist для необходимых npm install scripts (в
  первую очередь `esbuild`) после проверки одинакового поведения на Windows, macOS и
  Linux; не разрешать install scripts глобально.
- Вести матрицу минимальных версий Codex/Claude CLI. Для неподдерживаемых сохранённых
  model/effort показывать предупреждение и предлагать CLI default вместо тихого сбоя.
- Запускать authenticated provider smoke tests отдельным opt-in/manual workflow с
  короткими prompts, явным лимитом расходов и без доступа к пользовательским данным.

### Производительность и надёжность

- Превратить существующие long-session regression tests в измеряемый benchmark:
  бюджеты на размер snapshot/detail, число SQL queries, ingest latency, reconnect
  replay и время React update на 1/3/8-часовых синтетических сессиях.
- Добавить контролируемый fault-injection suite: kill service worker/provider/server
  в разных точках commit/ACK/streaming и проверять отсутствие потерь, дублей и
  осиротевших процессов.
- Автоматизировать подготовку release evidence: checksums, версии ОС/архитектуры,
  bounded logs и ссылки на CI должны формировать черновик строк для platform matrix,
  оставляя ручные native checks ручными.
- Для browser adapters хранить versioned DOM signatures и выводить раннее
  privacy-safe предупреждение при резком падении discovery confidence; каждое
  подтверждённое изменение Meet/Teams/Zoom превращать в минимальный fixture.

## Distribution и эксплуатация

- Добавить Windows code signing и macOS hardened runtime/notarization/stapling,
  когда появятся signing identities и защищённая release infrastructure.
- Опубликовать Chrome Web Store и Firefox AMO listings, заменить общие store URLs на
  прямые ссылки и добавить проверку установленных store builds в release matrix.
- После выбора RPM baseline добавить нативный smoke на поддерживаемом Fedora/RHEL-
  совместимом дистрибутиве; не считать успешную сборку доказательством совместимости.
- Рассмотреть system tray и OS autostart как отдельные opt-in функции с прозрачным
  управлением жизненным циклом daemon.
- Разрешить настраиваемый loopback port/address только как согласованное изменение
  manifests, pairing, origin/CORS policy, launcher и migration UX. Доступ из LAN или
  Internet должен оставаться отдельной security feature, а default - loopback-only.

## Возможности будущих версий

- Добавить новые `AgentProvider`: другие CLI и локальную/offline модель для встреч,
  где transcript нельзя отправлять облачному провайдеру.
- Добавить новые meeting adapters после появления реальных sanitized fixtures;
  desktop apps и системный audio/STT рассматривать как отдельную архитектуру, а не
  расширение DOM capture.
- Добавить полнотекстовый поиск по sessions и дополнительные экспорты: JSONL, SRT,
  VTT и выбранный диапазон transcript.
- Добавить опциональную коррекцию speaker/text, merge/split utterances с хранением
  оригинала и явным audit trail.
- Добавить автоматические session title/summary, список decisions/actions и export в
  внешние task/knowledge systems только по явному действию пользователя.
- Рассмотреть шифрование локальной БД/exports at rest. До реализации нужно решить
  key management, backup/recovery и поведение launcher при недоступном keyring.
- Добавить пользовательские action shortcuts, порядок/группировку кнопок и
  session-specific preset overrides, не меняя immutable snapshot уже запущенных runs.
