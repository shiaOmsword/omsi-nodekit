# Архитектура Nodekit

`framework` содержит общие механизмы без знания нод, клиентов 3x-ui и таблиц приложения.
`app` задаёт предметную модель и сценарии. Конкретные адаптеры подключает один composition
root — `app/container.py`. Сервисы получают зависимости через конструктор; контейнер
не передаётся в сущности и сценарии.

| Слой | Где | Ответственность |
| --- | --- | --- |
| Общие компоненты | `framework/database`, `network`, `entities`, `utils` | SQLite, транзакции/миграции, subprocess/SSH, фабрика, YAML/JSON, приватные файлы |
| HTTP и журнал | `framework/routing.py`, `framework/logging.py` | Формат ответов, обработчики исключений, создание router, контекстные JSON-логи |
| Предметная модель | `app/entities` | Node, SSH, Tunnel, Job/JobStatus, Backup, инварианты и создание записей |
| Порты | `app/ports.py` | Контракты репозиториев, файлов бэкапа, исполнителя, рендера и шаблона |
| Сценарии | `app/services` | Сохранить/проверить ноду, поставить задачу, выполнить её, импортировать бэкап |
| Адаптеры | `app/infrastructure` | SQL-схема и репозитории, файлы, генераторы, SSH-исполнитель и сборка remote bundle |
| Удалённая часть | `app/agent` | Подготовка VPS, БД панели, диагностика и развёртывание |
| Точки входа | `app/create_app.py`, `app/main.py`, `app/routes` | Lifespan, middleware, подключение маршрутов и запуск сервера |

Направление зависимостей: маршруты → сценарии → порты/сущности. Адаптеры реализуют порты.
`framework` не импортирует `app`; сценарии и сущности не импортируют FastAPI, sqlite3,
subprocess или конкретные адаптеры. Эти ограничения проверяются тестами.

## Публичные импорты

```python
from app.entities import Node, NodeFactory, Job, JobAction
from app.services import NodeService, JobService
from framework.entities import Entity, EntityFactory, JsonCodec, YamlCodec
```

`__init__.py` — публичный фасад с явным `__all__`. Внутри самого пакета leaf-модули
импортируют соседние модули напрямую: это убирает циклы и зависимость от порядка
инициализации фасада. Сторонние библиотеки не переэкспортируются через `app.entities`.

## Фабрика и сущности

`Entity` задаёт строгие неизменяемые Pydantic-модели. `EntityFactory.create`, `from_yaml`
и `from_json` строят произвольную модель с общей проверкой и безопасными ошибками.
`NodeFactory` добавляет ограничения приложения: размер YAML и число туннелей.

`StoredNode.create` считает revision; `Backup.create` — размер и SHA256;
`Job.create` создаёт задачу, а `Job.transition` запрещает недопустимые переходы состояния.
Это не универсальная ORM: сохранение явно выполняют репозитории.

## DI через punq

```python
settings = Settings()
container = build_container(settings, overrides={NodeExecutor: fake_executor})
service = container.resolve(JobService)
```

Регистрации есть только в `app/container.py`. Там интерфейсы связываются с SQLite,
файлами и SSH, а общие сервисы регистрируются как singleton. `overrides` позволяет
подставлять адаптеры в тестах до сборки графа. Контейнер принадлежит одному приложению;
несколько экземпляров не разделяют глобальные репозитории.

## Настройки и дефолты

- `app/defaults.py`: общие значения для сущностей ноды и константы формата 3x-ui.
  Конкретная нода переопределяет свои значения через YAML.
- `app/config.py`: типизированные настройки самого приложения: server, ssh, limits,
  deployment, пути данных. Рендер и удалённый агент получают одну и ту же policy.
- `.envs/.local.env`, `.envs/.staging.env` и т.д.: выбираются через переменную окружения
  `NODEKIT_ENVIRONMENT`. Значения окружения имеют приоритет над выбранным файлом.
- Вложенные поля задаются через `__`: `NODEKIT_SSH__OPERATION_TIMEOUT=900` или
  `NODEKIT_DEPLOYMENT__REMOTE_ROOT=/srv/nodekit`.

Названия ключей 3x-ui, структура Compose, HTTP-заголовки и защитная привязка backend
панели к localhost — часть поддерживаемого протокола, а не произвольные переключатели.
Docker host network сохраняется: смена этой схемы требует отдельной реализации транспорта.
Это относится к развёртыванию Nodekit; обнаружение существующих Docker-установок
также показывает bridge networks и published ports.

## SQLite

`framework.database.SQLiteDatabase` открывает и закрывает соединения, управляет транзакциями
и применяет переданные миграции по `PRAGMA user_version`. SQL находится только в
`app/infrastructure/schema.py` и репозиториях. Первая миграция подхватывает старую базу
версии 0 без удаления таблиц и данных. Выбор задачи и проверка revision выполняются
в одной `BEGIN IMMEDIATE` транзакции.

`SQLiteSnapshots` — отдельный общий компонент: он создаёт согласованный снимок, включая
WAL, и проверяет переданные требования к таблицам/колонкам. Набор таблиц 3x-ui задаёт
приложение. Данные бэкапа сохраняются атомарно; SHA256 проверяется перед восстановлением.

## Удалённый агент

`RemoteAgentBuilder` упаковывает `app/agent`, общие stdlib-компоненты SQLite и subprocess
в небольшой архив и передаёт bootstrap-код по SSH stdin. На VPS создаётся временный каталог,
из него импортируются модули, после выполнения он удаляется. Установка punq, FastAPI,
Pydantic или Poetry на VPS не требуется. Тест запускает bundle в Python с `-I -S`.

Контекст агента получает сериализованные policy/limits из локального Settings.
Сервисы HostEnvironment, PanelDatabase, Diagnostics и DeploymentService собираются явно
в RemoteAgent: на удалённой стороне для этого не нужен отдельный DI-контейнер.

## Ответы и ошибки

Все обычные JSON-ответы `/api` имеют формат:

```json
{"ok": true, "data": {"status": "ok"}, "error": null, "meta": {"request_id": "..."}}
```

```json
{"ok": false, "data": null, "error": {"code": "validation_error", "message": "Entity validation failed", "details": [{"field": "ssh.host", "code": "string_pattern_mismatch"}]}, "meta": {"request_id": "..."}}
```

`framework.entities` содержит типы ошибок без привязки к HTTP. Обработчики из
`framework.routing` сопоставляют их со статусами: validation 422, not_found 404,
conflict 409, payload_too_large 413, infrastructure 502, internal 500. Сюда же приводятся
ошибки схемы запроса, неизвестный маршрут и отказ middleware. Валидация не возвращает
исходные значения полей; неожиданные ошибки не раскрывают текст исключения.

`X-Request-ID` совпадает с `meta.request_id`; этот же контекст попадает в JSON-логи.
Фоновые операции добавляют `job_id` и `node_id`. Тела запросов, пароли, содержимое бэкапов
и строки исключений в системные логи не записываются. Читаемый журнал задач хранится отдельно.

Файлы `.db` и манифесты скачиваются обычным FileResponse: успешное скачивание сохраняет
исходные байты, а ошибки используют общий JSON-формат. Для dev-сервера Vite можно задать `NODEKIT_API_URL` и `NODEKIT_FRONTEND_DEV_PORT`
в `frontend/.env.local` (пример — `.env.example`).

`frontend/src/api.ts` распаковывает
envelope и создаёт ApiError с code, details, status и requestId; компоненты продолжают
работать с данными своего типа.

## Проверка

```bash
cd backend
poetry install --with dev
poetry run pytest -q
poetry run ruff check src tests
poetry run ruff format --check src tests
cd ../frontend
npm ci
npm test
npm run build
```

Архитектурные тесты, DI overrides и миграция старой БД дополняют проверки восстановления,
WAL, целостности бэкапа и HTTP-контракта. Реальное восстановление на VPS по-прежнему
нужно проверять отдельно с бэкапом и той же версией образа 3x-ui.

Системные тексты и общий frontend framework описаны в [messages.md](messages.md);
первый прогон на VPS — в [faq.md](faq.md).

## Существующие установки и SSH-ключи

`Installation` разделяет managed/auto/native/docker. `SystemInventory`, `PanelInspector`,
`CertificateInspector` и `CaddyInspector` в stdlib-only агенте читают существующую
конфигурацию. `ExistingDiagnostics` использует обнаруженный listener и проверяет HTTPS.
Сборка отчёта не вызывает deploy/reload. `ExecutionEvent` передаёт ровно один из
message/backup/report; локальная часть валидирует `InstallationReport` и сохраняет его
в `job_reports` через JobRepository. `JobDetails.report` доступен после перезапуска.

`SSHKeyService` работает через SSHKeyRepository/SSHKeyFiles. Общий OpenSSHKeys находится
в `framework/network/keys.py`: генерация, приватные файлы и ACL. LocalSSHKeyFiles связывает
его с приложением. SSHNodeExecutor разрешает `ssh.key_id` в локальный путь; приватное
содержимое не проходит через HTTP или сериализованный отчёт. Миграция v2 добавляет
таблицы ключей и отчётов. Регистрации — в том же punq composition root.

Frontend feature-компоненты находятся в `src/features/keys`, `nodes`, `help`.
CodeBlock с копированием и общие form styles находятся в `src/framework/components`;
системные подписи — в framework/messages, предметные методички — в features/help/guides.ts.
Полные сценарии и ограничения: [existing-nodes.md](existing-nodes.md).
