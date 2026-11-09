# Руководства OMSI Nodekit

Инструкции относятся к ветке **`dev`**, а не к произвольной старой установке
или релизу `main`. Последняя сверка с кодом: **9 ноября 2026 года**;
[основания и ограничения проверки](documentation-audit.md).

Nodekit запускается локально. На VPS нужен Python 3.11+ со стандартной
библиотекой, SSH-доступ и root либо sudo. Poetry/FastAPI на VPS не нужны.
Тип установки для обнаружения (`panel.installation`) и целевое окружение
(`deployment`) — разные настройки.

## Выбрать задачу

| Задача | Руководство |
| --- | --- |
| Запустить приложение, настроить SSH и sudo | [Первый запуск](faq.md), [существующие ноды](existing-nodes.md) |
| Создать новую native/Docker-панель | [Развёртывание](adaptive-deployment.md) |
| Открыть админку по SSH или HTTPS с ограничением доступа | [Доступ к 3x-ui](panel-access.md) |
| Подключить Caddy после установки, изменить подписки | [Подписки и Caddy](subscriptions.md) |
| Проверить выдачу подписок или сбросить серверный кэш | [Обслуживание подписок](subscription-maintenance.md) |
| Создать XHTTP/TLS и опубликовать внешний endpoint в Hosts | [VLESS / XHTTP / TLS](working-transports.md) |
| Создать WG, добавить peer, восстановить WG из 3x-ui | [WireGuard](wireguard.md) |
| Перенести wg-easy v15, сохранить ключи и сменить Endpoint | [Миграция WireGuard](wireguard-migration.md) |
| Подготовить SSH-выходы, балансировщик и общий маршрут | [SSH-egress](ssh-egress.md) |
| Проверить UFW/порты, измерить скорость, применить BBR/CUBIC | [Управление сетью](network-management.md), [замеры](network-benchmarks.md), [TCP](tcp-congestion-control.md) |
| Восстановить панель и параметры на новой VPS | [Системные архивы](system-backups.md), [окружение назначения](restore-targets.md) |
| Проверить backup и выборочно перенести VLESS-клиентов | [Репетиция восстановления](restore-rehearsal.md) |

## Установка и восстановление

- `fresh` и `restore` создают панель на **пустой** целевой VPS/в пустом каталоге;
  ими нельзя обновлять уже работающую панель.
- `.db` 3x-ui содержит данные панели; `.nodekit.zip` дополнительно содержит
  поддерживаемые системные настройки и приватные ключи туннелей. Это не образ ОС.
- `.db` wg-easy v15 используется только для выборочного переноса WG inbound,
  а не для восстановления всей 3x-ui.
- Сохранение YAML меняет локальную конфигурацию. Для VPS нужен соответствующий
  план и запуск операции; универсального `apply` нет.
- Успешный план, TCP listener или локальный HTTPS-запрос не заменяют проверку
  VPN, DNS и выходного IP с реального клиентского устройства.

## Для разработчика

[Архитектура](architecture.md), [интерфейс](frontend-workspace.md),
[каталоги сообщений](messages.md), [текущие границы и roadmap](deployment-roadmap.md),
[Contributing](../CONTRIBUTING.md), [Security](../SECURITY.md),
[Changelog](../CHANGELOG.md), [подготовка выпуска](release-checklist.md).
[Первоначальный замысел](project.md) сохранён как исторический материал.

Навигация GitBook хранится в [SUMMARY.md](../SUMMARY.md), а `.gitbook.yaml`
явно выбирает существующий `readme.md` главной страницей. Эти файлы готовят
репозиторий к Git Sync; само подключение сайта/space выполняется отдельно в GitBook.
