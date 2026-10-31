# Проверенные подключения Москвы

31.10.2026 пользователь подтвердил подключение с телефона по VLESS + XHTTP + TLS.
Использовать как проверенный альтернативный вход, когда прямой RAW/REALITY нестабилен.
Автоматическое создание XHTTP inbound пока не реализовано.

## Два независимых участка

- Телефон → Москва: VLESS/RAW/REALITY либо VLESS/XHTTP/TLS.
- Москва → выходная нода: VLESS/RAW/REALITY внутри SSH local forwarding.

Обычный TLS и REALITY — разные варианты security, а не два включённых одновременно поля.

## Рабочий рецепт XHTTP + TLS

Для ultra: Caddy в Docker, bridge shared-proxy, gateway 172.30.50.1,
подсеть 172.30.50.0/24. В рецепте домен vpn.brainoms.ru, A → 5.253.62.214.
Перед повторной установкой сверять текущие DNS, IP и интерфейс bridge.

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
vpn.brainoms.ru {
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

Клиент: vpn.brainoms.ru:443, UUID нового клиента, transport xhttp,
path /xhttp-ultra/, mode auto, TLS включён, SNI vpn.brainoms.ru,
ALPN h2, проверка сертификата включена, flow пустой, обычный Mux выключен.
Для сравнения можно отдельно попробовать packet-up на клиенте.
REALITY public key/short ID в этом внешнем профиле не используются.

Панель может сформировать внутренний endpoint 172.30.50.1:10080/security=none.
Для выдачи правильного публичного профиля через подписку требуется Host override
в 3x-ui: домен, порт 443, security tls, SNI и тот же XHTTP path.

## Подписки — отдельная цепочка

https://brainoms.ru:2096/sub/<client-id> → shared-caddy →
http://172.30.50.1:2097/sub/<client-id>. Не смешивать порты подписки с VPN inbound.
UUID, приватные ключи и реальные ID подписок не сохраняются в документации.

## Выводы диагностики

Тот же RAW/REALITY профиль с неизменными UUID, SNI и ключами стабильно работал
через SSH-forward клиента к loopback:8443 Москвы, но напрямую были таймауты.
Это указывает на различие внешнего пути/транспорта; конкретно DPI этим не доказан.
Успешная локальная проба Nodekit не доказывает доступность телефона → Москва.
После изменения серверного маршрута проверять сайты и внешний IP на телефоне.
