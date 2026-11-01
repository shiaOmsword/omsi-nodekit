# SSH-выход для установленной панели

Нода → **Inbound → SSH-выход**. Доступно для активной панели 3x-ui 3.11.0,
установленной Nodekit и имеющей manifest. Работа с панелью в системе и Docker
с host network одинакова. XHTTP на входе Москвы совместим с этим сценарием:
внешний транспорт телефона независим от межсерверного RAW/REALITY внутри SSH.

## Подготовка

1. На выходной VPS создать VLESS/RAW/REALITY inbound и клиента. Inbound должен
   принимать соединения на **127.0.0.1:8443** выходной VPS (порт можно выбрать другой).
2. В 3x-ui Москвы добавить обычный VLESS/RAW/REALITY outbound с параметрами этого
   клиента: UUID, flow, SNI, public key и short ID. Операция использует его как
   источник настроек и оставляет исходную запись неизменной. Автоматического
   импорта клиента из другой панели в этой версии нет.
3. На **московской VPS** подготовить SSH-ключ без интерактивной passphrase;
   добавить его публичную часть в authorized_keys пользователя выходной VPS.
   Пути identity_file/known_hosts_file ниже относятся к московской VPS,
   а не к компьютеру, где запущен Nodekit. Пользователь tunnels.user должен
   существовать на обеих VPS; на Москве от его имени запускается служба SSH.
4. Записать проверенный host key выходной VPS в known_hosts. Для нестандартного
   порта SSH запись должна соответствовать `[host]:port`. Private key обычно
   имеет права 600 и принадлежит пользователю службы. В SSHD выходной VPS
   разрешить local TCP forwarding к 127.0.0.1:8443. Для ключа с `restrict` отдельно
   разрешить `port-forwarding,permitopen="127.0.0.1:8443"`.
5. Добавить tunnels в существующий YAML Москвы, сохранив остальные параметры:

```yaml
tunnels:
  - name: gb
    host: 203.0.113.20  # заменить адресом выходной VPS
    user: omsi
    ssh_port: 2222     # фактический SSH-порт выходной VPS
    local_port: 15443
    target_port: 8443
    identity_file: /home/omsi/.ssh/gb_xray_tunnel
    known_hosts_file: /home/omsi/.ssh/known_hosts
```

У каждого туннеля должны быть уникальные name и local_port; имя panel
зарезервировано. Порт local_port публично в UFW открывать не требуется.
Если исходный inbound выхода доступен только внутри изолированной Docker-сети,
сначала обеспечить его доступность с loopback выходной VPS.

## Применение

Сохранить YAML → обновить обнаружение → Inbound → SSH-выход.
Выбрать туннель, outbound выходной ноды и inbound Москвы, посмотреть план,
затем запустить операцию. Все клиенты выбранного inbound будут использовать
этот выход. Для сохранения российского IP оставить отдельный inbound на direct.

Операция:

- проверяет fingerprint inbound и принадлежность systemd-службы;
- сохраняет приватные SQLite и Xray template snapshots на VPS;
- включает loopback-only SSH-forward с StrictHostKeyChecking, IdentitiesOnly,
  BatchMode, ExitOnForwardFailure, keepalive и Restart=always;
- использует `-F none`, исключая скрытые LocalForward/ProxyCommand из SSH config;
- получает непустой HTTPS-ответ через настоящий выходной VLESS inbound;
- создаёт outbound `ssh-<node>-<tunnel>` с локальным SSH endpoint; UUID, SNI,
  ключи, short ID и flow сохраняются;
- добавляет маршрут только выбранного inbound после начальных API/blackhole
  правил, сохраняя исходный outbound, default outbound и остальные правила;
- сохраняет template через API, перезапускает Xray и сверяет runtime;
- при ошибке откатывает template и состояние службы. Если template параллельно
  изменил оператор, чужие изменения не затираются: выводится ошибка отката,
  рабочий forward сохраняется для текущего маршрута.

Повторное применение тех же параметров допустимо; при этом порядок имеющихся
outbound и правил сохраняется. Один туннель привязывается к одному inbound.
Смена inbound через существующую запись отклоняется, чтобы молча не снять
старый маршрут. Изменение порта того же inbound отслеживается по его ID и
обновлённому тегу 3x-ui. Manifest фиксирует только применённые туннели: если
в YAML добавлено несколько новых записей, применить каждую перед следующей
настройкой подписок. Чужая или изменённая systemd-служба не перезаписывается.
Службы прежнего формата без `-F none` требуют ручного согласования конфигурации.

## Проверка и восстановление

Доктор проверяет systemd и loopback listener туннелей из YAML. SSH-выход
дополнительно проверяет UUID/REALITY, передачу запроса и получение HTTPS-ответа.
Проверка не доказывает внешнюю доступность телефона и не проверяет геолокацию IP.
После применения открыть сайты и проверить внешний IP на телефоне:
ожидается IP выбранной выходной VPS.

Для возврата: в 3x-ui убрать правило с outboundTag `ssh-<node>-<tunnel>`
или направить выбранный inbound на direct. Затем можно остановить службу
`omsi-<node>-<tunnel>.service`. Предыдущий template и SQLite сохранены как
`before-tunnel-<timestamp>.json` и `.db` в каталоге ноды; эти файлы приватные.
Удаление записи ноды из локальной панели не удаляет удалённую SSH-службу.

SSH `-L` переносит TCP. Сырой UDP-порт он не открывает: UDP-приложения требуют
совместимого переноса UDP внутри VLESS и поддержки этого режима клиентом.

## Границы этой версии

Требуются подготовленные межсерверный SSH-ключ, known_hosts и исходный
outbound. Автоматическая выдача ключей/authorized_keys, импорт клиентов
между панелями, создание произвольных XHTTP outbound и кросс-провайдерный failover
в этот PR не входят. Guarded XHTTP ingress и SSH-пул описаны выше;
первый live прогон ещё не подтверждён. Безопасность RAW/REALITY относится к межсерверному
участку и не меняет проверенный XHTTP/TLS профиль телефона.

## Воспроизводимый локальный smoke

`backend/tests/runtime/ssh_exit_smoke.py` создаёт временные панели, ключи и
loopback listeners. Проверяет XHTTP/TLS → Caddy → московская 3x-ui → OpenSSH
клиент → выходной REALITY → HTTPS и получает полный ответ 188416 байт.
Проверяется и повторное применение. systemctl симулируется; настоящий
OpenSSH исполняет сгенерированный ExecStart. Публичная VPS не используется.

В одноразовой Linux root-среде с бинарниками 3x-ui, Xray, Caddy и sshd:

```bash
cd backend
PYTHONPATH=src poetry run python tests/runtime/ssh_exit_smoke.py \
  --panel /path/to/x-ui \
  --xray /path/to/bin/xray-linux-amd64 \
  --caddy /path/to/caddy \
  --sshd /usr/sbin/sshd
```

Для OpenSSH server backend нужен `/run/sshd`. Если контейнер запрещает
`setgroups`, можно отдельно установить **только в тестовую среду**
`paramiko==5.1.0` и вместо `--sshd` передать `--ssh-backend paramiko`.
Тогда сервером выступает настоящий SSH fixture на Paramiko, а проверка
читаемости файлов root через runuser заменяется os.access. SSH-клиент,
3x-ui, Xray, TLS и весь трафик остаются настоящими. В приложении Paramiko
не используется и не добавляется в production dependencies.


## Форматы VLESS и сообщения preflight

SSH-выход поддерживает плоские settings (`address`, `port`, `id`, `encryption`,
`flow`, `testseed`) и прежний `vnext` с одним endpoint и списком пользователей.
Исходный формат сохраняется; меняются только tag копии, адрес и порт назначения.
Смешивать обе схемы в одном outbound нельзя. UUID, REALITY, flow и testseed
сохраняются без изменений. В runtime smoke по умолчанию проверяется плоский
outbound; `--outbound-format vnext` повторяет проверку прежнего формата.

При отказе подготовки журнал показывает конкретную известную проверку:
формат outbound, актуальность inbound, принадлежность маршрута/службы,
доступность ключа/known_hosts или занятый порт. Неожиданные ошибки показывают
подэтап и класс исключения. Полные settings, ответы API, UUID и приватные ключи
в журнал не выводятся. Preflight выполняется до запуска новой службы, поэтому
пустой systemd journal при таком отказе возможен. После обновления Nodekit
обновить обнаружение и заново открыть модалку SSH-выхода.

## Пул независимых SSH-сессий (новый экспериментальный сценарий)

Вкладка **Нода → SSH-туннели** показывает записи `tunnels` из YAML и
read-only systemd status на VPS. Если настроен только один SSH-выход, кнопка
**«Подготовить 3 в YAML»** создаёт две копии с новыми именами и локальными
портами. Это изменяет только локальную конфигурацию Nodekit, а не VPS.
Сверить порты, сохранить настройки, обновить обнаружение, затем
**«Поднять пул»**.

Пример — три независимых процесса `ssh -N -T`, с одним и тем же exit VLESS:

```yaml
tunnels:
  - name: nd
    host: 203.0.113.20
    user: omsi
    ssh_port: 2222
    local_port: 15443
    target_port: 11474
    identity_file: /home/omsi/.ssh/ultra_gb_tunnel
    known_hosts_file: /home/omsi/.ssh/known_hosts
  - name: nd-2
    host: 203.0.113.20
    user: omsi
    ssh_port: 2222
    local_port: 15444
    target_port: 11474
    identity_file: /home/omsi/.ssh/ultra_gb_tunnel
    known_hosts_file: /home/omsi/.ssh/known_hosts
  - name: nd-3
    host: 203.0.113.20
    user: omsi
    ssh_port: 2222
    local_port: 15445
    target_port: 11474
    identity_file: /home/omsi/.ssh/ultra_gb_tunnel
    known_hosts_file: /home/omsi/.ssh/known_hosts
```

В мастере пула указать имя, участников, существующий исходный
VLESS/RAW/REALITY outbound и московский inbound. Каждый SSH unit проверяется
на владение/уникальность и поднимается отдельно. Через каждый путь
проверяется реальный HTTPS body. Затем Nodekit создаёт клоны outbounds,
балансировщик `roundRobin` с `observatory` и `fallbackTag: blocked`,
маршрут только выбранного inbound. Важный момент: `observatory` должен
находиться **на верхнем уровне Xray JSON**, а `balancers` — внутри
`routing`. Метаинформация приватно сохраняется в `pool-<name>.json`.

Текущий сценарий допускает миграцию одного ранее управляемого одиночного
туннеля, если его SSH unit, outbound и route не меняли посторонние.
Остальные туннели создаются как отдельные systemd services. При
несогласованном владельце, занятом порте, недоступном ключе или
непройденной HTTPS-пробе операция останавливается/откатывается.

**Что пул не гарантирует:** три SSH-сессии до одного хоста не защищают
от отказа самой exit VPS, а существующие TCP-соединения не переносятся
на другую сессию при её падении. Кросс-провайдерный failover,
управление SSH-ключами и интерактивное удаление/перенос членов пула
пока не реализованы. При падении всех выходов не допускается silent
fallback на московский direct.

Изменение Xray template происходит через API 3x-ui. До проверки
реальной VPS и полного интеграционного smoke считать этот механизм
новым экспериментальным сценарием и не переводить на него сразу
единственный рабочий клиентский inbound.

## Первый SSH host key: строгая проверка и опциональный TOFU

Подключение с рабочего ПК не заполняет
`/home/omsi/.ssh/known_hosts` на **московской VPS**.
Сервер `78.17.45.177` на портах `22` и `2222` обычно имеет
разные записи в `known_hosts`: для стандартного порта `78.17.45.177`,
для нестандартного `[78.17.45.177]:2222`.
Из-за `StrictHostKeyChecking=yes` и `BatchMode=yes` первый
неизвестный host key блокирует systemd SSH forward без приглашения.

По умолчанию Nodekit сохраняет строгую проверку. Чтобы один **новый**
SSH endpoint мог принять ключ сервера при первом соединении,
явно добавь в YAML конкретного туннеля:

```yaml
  - name: nd-3
    host: 78.17.45.177
    user: omsi
    ssh_port: 22
    local_port: 15445
    target_port: 11474
    identity_file: /home/omsi/.ssh/ultra_gb_tunnel
    known_hosts_file: /home/omsi/.ssh/known_hosts
    host_key_policy: accept-new
```

Это включает `StrictHostKeyChecking=accept-new` и сохраняет `BatchMode=yes`
и `IdentitiesOnly=yes`. **Новый** host key сохраняется в `known_hosts`,
а если известный fingerprint **изменился**, OpenSSH разрывает соединение.
`StrictHostKeyChecking=no` не используется. В режиме TOFU пользователь
SSH-службы должен иметь право записи в свой `known_hosts` или его
родительский каталог (если файла пока нет). Символьные ссылки в TOFU
запрещены. По соображениям безопасности этот режим не включён по
умолчанию: на первом подключении возможна атака посредника; для
критичных нод лучше проверить fingerprint через независимый канал.

Проверить с московской VPS без изменения Nodekit:

```bash
ssh-keygen -F 78.17.45.177 -f /home/omsi/.ssh/known_hosts
ssh-keygen -F '[78.17.45.177]:2222' -f /home/omsi/.ssh/known_hosts

ssh -F none -p 22 -i /home/omsi/.ssh/ultra_gb_tunnel \
  -o UserKnownHostsFile=/home/omsi/.ssh/known_hosts \
  -o StrictHostKeyChecking=yes \
  -o IdentitiesOnly=yes -o BatchMode=yes -v \
  omsi@78.17.45.177 true
```

Если неизвестный host key — будет `Host key verification failed`.
Если отклонён ключ пользователя — `Permission denied (publickey)`.
Если TCP forwarding запрещён на выходной VPS — проверить настройки
`AllowTcpForwarding`, `PermitOpen`, ограничения в `authorized_keys`
и `journalctl -u omsi-ultra-nd-3.service`.

Важное ограничение: на уже существующем systemd unit изменение
`host_key_policy` меняет `ExecStart`. Nodekit намеренно не
перезаписывает unit, если он отличается от сгенерированного. Для
применения новой политики к ранее созданной службе требуется
контролируемое обновление только доказанно принадлежащего Nodekit unit.
