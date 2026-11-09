# Сверка документации с кодом

Дата: **9 ноября 2026 года**. Основа: ветка `dev`, commit
[`d44b16e`](https://github.com/shiaOmsword/omsi-nodekit/commit/d44b16e8e3e68aef8b3f9d4f4eeee3a6586bb1fb).
В момент проверки `main` находился на `e7d77f5` и отставал от `dev`.
Этот документ фиксирует проверенную версию, а не обещает актуальность будущих изменений.

## Результат

Документация частично актуальна: специализированные страницы описывают новые
операции, но FAQ, обзор возможностей и ранний roadmap отставали. Из-за этого
готовые действия назывались будущими задачами или имели противоречивые инструкции.

| Область | Исправление | Основание в репозитории |
| --- | --- | --- |
| Ветки и запуск | README явно относится к `dev`; clone выбирает её | [Contributing](../CONTRIBUTING.md), workflow репозитория |
| Навигация | Добавлены индекс всех руководств, SUMMARY и выбор `readme.md` для GitBook | [Оглавление](../SUMMARY.md), `.gitbook.yaml` |
| Обзор функций | Добавлены WG, wg-easy v15, архивы, BBR/замеры и защищённый вход | [JobAction](../backend/src/app/entities/records.py), [agent dispatcher](../backend/src/app/agent/runtime.py) |
| Подстановка из отчёта | Уточнено: кнопка сохраняет локальную ноду, но не меняет VPS | [applySuggestions](../frontend/src/App.tsx), [DiscoveryModal](../frontend/src/features/nodes/DiscoveryModal.tsx) |
| Runtime и defaults | Managed включает native/Docker; интерфейс предлагает Docker + Caddy | [DeploymentTarget](../backend/src/app/entities/deployment.py), [defaultTarget](../frontend/src/app/config.ts) |
| Fresh/Restore | Пустая панель только при пустом inbounds; Restore читает пути из backup | [AdaptiveDeployment](../backend/src/app/agent/adaptive_deployment.py), [DeploymentModal](../frontend/src/features/nodes/DeploymentModal.tsx) |
| Подписки | Подключение Caddy и configure отделены от миграции runtime/образа | [ConfigureSubscriptions](../backend/src/app/agent/configure.py), [AttachmentCaddy](../backend/src/app/agent/attach_caddy.py) |
| XHTTP | Убрано утверждение об отсутствии публикации Hosts; это отдельная операция | [XHTTPManager.publish_host](../backend/src/app/agent/xhttp_manager.py) |
| SSH и routing | FAQ ссылается на подготовку туннеля/пула, балансировщик и маршрут | [TunnelSetup](../backend/src/app/agent/tunnel_setup.py), [Xray routing](../backend/src/app/agent/xray_routing.py) |
| Caddy и UFW | Reload сайта отделён от пересоздания контейнера ради портов | [Caddy port reconciliation](../backend/src/app/agent/caddy_ports.py), [FirewallTransaction](../backend/src/app/agent/firewall.py) |
| Panel backend | Loopback по умолчанию; приватный gateway для защищённого bridge Caddy | [panel_bind](../backend/src/app/agent/panel_access.py) |
| Архивы и WG | Убраны устаревшие замечания о независимых ветках; уточнён состав ZIP | [System backup](../backend/src/app/agent/system_backup.py), [WG backup](../backend/src/app/backup_wireguard.py) |
| Встроенная справка | Исправлены требования runtime, пустой Fresh и публикация XHTTP | [guides.ts](../frontend/src/features/help/guides.ts) |

Проверка охватывает README на двух языках, все страницы `docs/`, embedded help,
пример YAML, типизированные модели, диспетчер операций, соответствующие удалённые
обработчики, интерфейс подготовки планов и CI. Исторический `project.md` оставлен
с явной пометкой; release checklist остаётся списком задач, а не отчётом о выпуске.

## Границы проверки

- Изменены документация, GitBook-навигация и текст встроенной справки.
  Поведение удалённых операций и production-конфигурации не менялись.
- В рамках аудита SSH/VPS, DNS, firewall, сертификаты и пользовательские
  VPN-профили не изменялись; новый live тест не проводился.
- Автотесты и локальные схемы не подтверждают внешний WG handshake,
  доступность телефона или полное восстановление произвольного backup.
- GitBook API вернул пустой список организаций для текущего подключения.
  Рендер на сайте и Git Sync в этом аудите не проверены; конфигурация импорта
  подготовлена в репозитории. Публикация сайта требует доступного space.

## Локальная верификация правок

| Проверка | Результат |
| --- | --- |
| Markdown и навигация | 31 файл; 178 относительных ссылок/якорей разрешаются; 29 уникальных страниц SUMMARY, все страницы `docs/` включены |
| YAML | 11 полных/частичных Node-примеров проходят текущую модель; отдельно проверен `backend/config/config-example.yaml` |
| Backend | `ruff check`, `ruff format --check`; pytest: **380 passed, 1 skipped**; sdist/wheel собраны |
| Frontend | **56 тестов passed**; TypeScript/Vite build успешен после правок embedded help |
| Diff | `git diff --check` без ошибок; production-операции не запускались |

В локальной среде остаются предупреждения зависимостей: deprecation
Starlette/httpx и размер frontend chunk свыше 500 kB. Они не блокируют
проверки и не исправлялись в задаче документации. Проверку GitHub Actions
нужно смотреть на окончательном HEAD PR; таблица выше описывает локальный прогон.
