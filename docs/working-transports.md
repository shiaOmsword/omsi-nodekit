# Пример: VLESS / XHTTP / TLS с Caddy

Ниже — схема построения VLESS/XHTTP/TLS ingress для собственной VPS, когда
прямой VLESS/RAW/REALITY нестабилен. Параметры заменены учебными значениями
для публичного репозитория; они **не являются готовой конфигурацией чужой ноды**.
Мастер Nodekit работает с подтверждённо управляемыми inbound и Caddy-маршрутами,
не присваивая вручную созданные чужие ресурсы.

## Два независимых участка

- Телефон → Москва: VLESS/RAW/REALITY либо VLESS/XHTTP/TLS.
- Москва → выходная нода: VLESS/RAW/REALITY внутри SSH local forwarding.

Обычный TLS и REALITY — разные варианты security, а не два включённых одновременно поля.

## Рабочий рецепт XHTTP + TLS

Пример: Caddy в Docker, bridge `shared-proxy`, gateway `172.30.50.1`,
подсеть `172.30.50.0/24`; домен `vpn.example.com`, A → `203.0.113.10`.
Адреса `example.com` и диапазон `203.0.113.0/24` зарезервированы для документации.
Замените их своими и проверьте интерфейс/gateway Docker перед применением.

3x-ui inbound:

| Поле | Значение |
| --- | --- |
| Протокол | VLESS |
| Listen | 172.30.50.1 |
| Порт | 10080 |
| Транспорт | XHTTP |
| Path | /xhttp-ultra/ |
| Mode | auto |
| Security на backend | none |
| VLESS encryption/decryption | none |
| Flow клиента | пусто |

Добавочный сайт общего Caddy, с сохранением остальных сайтов:

```caddyfile
vpn.example.com {
    @xhttp path /xhttp-ultra/*
    handle @xhttp {
        reverse_proxy h2c://172.30.50.1:10080 {
            flush_interval -1
        }
    }
    handle {
        respond "OK" 200
    }
}
```

Не использовать handle_path: он удаляет нужный префикс XHTTP.
Caddy публикует 80/TCP и 443/TCP; публичные firewall разрешают их.
10080 разрешён только от Caddy bridge к 172.30.50.1, без публичного открытия.
TLS завершает Caddy. Сертификат не нужно копировать внутрь Xray.

Клиент: vpn.example.com:443, UUID нового клиента, transport xhttp,
path /xhttp-ultra/, mode auto, TLS включён, SNI vpn.example.com,
ALPN h2, проверка сертификата включена, flow пустой, обычный Mux выключен.
Для сравнения можно отдельно попробовать packet-up на клиенте.
REALITY public key/short ID в этом внешнем профиле не используются.

Панель может сформировать внутренний endpoint 172.30.50.1:10080/security=none.
Для выдачи правильного публичного профиля через подписку требуется Host override
в 3x-ui: домен, порт 443, security tls, SNI и тот же XHTTP path.

## Подписки — отдельная цепочка

https://sub.example.com:2096/sub/<client-id> → shared-caddy →
http://172.30.50.1:2097/sub/<client-id>. Не смешивать порты подписки с VPN inbound.
UUID, приватные ключи и реальные ID подписок не сохраняются в документации.

## Выводы диагностики

Тот же RAW/REALITY профиль с неизменными UUID, SNI и ключами стабильно работал
через SSH-forward клиента к loopback:8443 Москвы, но напрямую были таймауты.
Это указывает на различие внешнего пути/транспорта; конкретно DPI этим не доказан.
Успешная локальная проба Nodekit не доказывает доступность телефона → Москва.
После изменения серверного маршрута проверять сайты и внешний IP на телефоне.

## Новый мастер Nodekit

Вкладка **Нода → Inbound → + VLESS / XHTTP** предлагает remark, HTTPS-домен,
приватный порт (обычно 10080), path, mode и имя первого клиента. На VPS
Nodekit создаёт inbound через 3x-ui API, добавляет только собственный site
в общий Caddy, разрешает соединение Caddy bridge → host backend в UFW,
сохраняет SQLite snapshot и приватный ownership metadata. При редактировании
собственного XHTTP сохраняет клиентов и их UUID/subId.

Заведомо чужие домены/Caddy routes и непроверенные источники не
переписываются. После операции всё равно сверить публичный TLS/DNS,
работоспособность телефона и **Hosts override** для подписок (автоматическое
изменение override ещё не реализовано). Если исходный XHTTP был создан
вручную, для него доступно управление клиентами и общим названием, но
не takeover Caddy без явной процедуры импорта.

См. `docs/restore-rehearsal.md` для резервирования базы и sidecar,
включая SSH units и shared Caddy.

## Публикация существующего XHTTP в подписке 3x-ui 3.11.0

После создания XHTTP вручную не требуется переделывать inbound и Caddy.
Открой `Inbound → Изменить` для XHTTP: Nodekit предложит **«Опубликовать
XHTTP в подписке»**. Операция использует `/panel/api/hosts/add` либо
`hosts/update/:groupId` и помечает только свою запись `Hosts`:
`nodekit:<node>:host:<inbound-id>`. Привязка inbound сохраняется в приватном
`xhttp-hosts.json`; чужие Hosts не удаляются. Перед операцией создаётся
SQLite snapshot.

Публичная запись имеет address `vpn.example.com`, port `443`,
security `tls`, SNI `vpn.example.com`, ALPN `h2`, path
`/xhttp-ultra/`, fingerprint `chrome`; Xray остаётся на
`172.30.50.1:10080` с `security=none`.
После публикации запроси **именно URL подписки клиента**
`https://sub.example.com:2096/sub/<subId>`, а не кнопку копирования
локального backend inbound из 3x-ui. Формат сырого `vless://`
в ответе подписки должен указывать на `vpn.example.com:443`
с `security=tls`, `sni=vpn.example.com`, `type=xhttp`.

Не перепутай подписку (subId) с UUID VLESS клиента. При ручной настройке
других Hosts для этого inbound Nodekit не присваивает их и откажется
заменять запись с таким же доменом. Если клиентские индивидуальные
Host bindings заданы вручную, их также необходимо проверить.
