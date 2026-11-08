import { useEffect, useState } from 'react';
import { parse } from 'yaml';
import type { Backup, InboundFinding, JobOptions, NodeRecord } from '../../types';
import { api } from '../../api';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

type Source = { id: number; remark: string; port: number; client_count: number;
  source_format?: 'wg-easy-v15'; interface?: string; endpoint?: { host: string; port: number };
  mtu?: number; dns?: string; subnet?: string; ipv6_subnet?: string; blockers?: string[];
  clients: { email: string; has_private_key: boolean; name?: string; enabled?: boolean;
    addresses?: string[]; expiry_time?: number }[] };

const incompatibilities: Record<string, string> = {
  server_hooks: 'Нестандартные серверные hooks',
  firewall: 'Фильтрация трафика клиентов wg-easy',
  routing_table: 'Особая таблица маршрутизации',
  client_dns: 'Индивидуальные DNS клиентов: в этом inbound 3x-ui DNS общий',
  client_mtu: 'Различающиеся MTU сервера, клиентов или настройки по умолчанию',
  client_routes: 'Особые клиентские AllowedIPs: выдача профилей 3x-ui использует полный туннель',
  server_routes: 'Маршруты сетей за клиентами',
  server_endpoint: 'Фиксированные серверные Endpoint клиентов',
  client_hooks: 'Hooks в клиентских профилях',
  gateway_dns: 'DNS внутри старой WG-подсети: его сервис нужно перенести отдельно',
};

export function WireGuardModal({ record, inbound, backups, busy, error, onClose, onPreview }: {
  record: NodeRecord; inbound?: InboundFinding; backups: Backup[]; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions, backupId?: string) => void;
}) {
  const [values, setValues] = useState<FormValues>({ operation: 'create',
    remark: inbound?.remark || 'wg-' + record.id,
    domain: inbound?.wg_domain || parse(record.yaml)?.caddy?.domain || parse(record.yaml)?.ssh?.host || '',
    port: String(inbound?.port || 51820), mtu: String(inbound?.wg_mtu || 1420),
    dns: inbound ? (inbound.wg_dns || '') : '1.1.1.1', subnet: '10.77.0.0/24', client_email: 'client-wg',
    backup_id: '', source_inbound_id: '', source_ipv6: '',
  });
  const [sources, setSources] = useState<Source[]>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(false);
  const restore = !inbound && values.operation === 'restore';
  useEffect(() => {
    let active = true;
    setSources([]); setCatalogError(''); setLoading(false);
    if (!restore || !values.backup_id) return;
    setLoading(true);
    api<Source[]>('/backups/' + values.backup_id + '/wireguard').then(items => {
      if (!active) return;
      setSources(items);
      setValues(v => ({ ...v, source_inbound_id: items[0] ? String(items[0].id) : '',
        source_ipv6: '', port: items[0] ? String(items[0].port) : v.port }));
    }).catch(() => { if (active) setCatalogError('WireGuard в этом бэкапе не прочитан. Проверь схему и ключи.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [values.backup_id, restore]);
  const selected = sources.find(s => s.id === Number(values.source_inbound_id));
  const wgEasy = restore && selected?.source_format === 'wg-easy-v15';
  const fields: FormField[] = [
    ...(!inbound ? [{ name: 'operation', label: 'Сценарий', type: 'select', options: [
      { value: 'create', label: 'Новый inbound и клиент' }, { value: 'restore', label: 'Перенести WG из 3x-ui / wg-easy v15' },
    ] } as FormField] : []),
    ...(restore ? [
      { name: 'backup_id', label: 'Бэкап 3x-ui, wg-easy.db или Nodekit ZIP', type: 'select', required: true,
        options: [{ value: '', label: 'Выбери бэкап' }, ...backups.map(b => ({ value: b.id, label: b.filename }))] },
      { name: 'source_inbound_id', label: loading ? 'Чтение WG…' : 'Исходный WG inbound', type: 'select', required: true,
        options: sources.map(s => ({ value: String(s.id), label: `#${s.id} · ${s.remark} · ${s.client_count} клиентов` })) },
    ] as FormField[] : []),
    ...(wgEasy ? [{ name: 'source_ipv6', label: 'Режим исходного wg-easy', type: 'select', required: true,
      options: [{ value: '', label: 'Выбери по результату экспорта' },
        { value: 'true', label: 'WireGuard · source_ipv6: true' },
        { value: 'false', label: 'WireGuard · source_ipv6: false' }],
      hint: 'Укажи source_ipv6 из tools/export_wg_easy.py. SQLite не хранит DISABLE_IPV6. AmneziaWG не поддерживается.',
    } as FormField] : []),
    { name: 'remark', label: 'Название inbound', required: true, maxLength: 120 },
    { name: 'domain', label: 'Новый WG endpoint: IP или домен', required: true,
      hint: 'Укажи адрес новой VPS. Для домена нужна A-запись на неё. WG использует отдельный UDP-порт.' },
    { name: 'port', label: 'Публичный UDP-порт', type: 'number', required: true, min: 1, max: 65535,
      hint: 'Для старых конфигов сохрани прежний порт. 443/udp может быть занят QUIC Caddy.' },
    ...(!restore ? [
      { name: 'mtu', label: 'MTU', type: 'number', required: true, min: 576, max: 1500 },
      { name: 'dns', label: 'DNS в клиентском профиле', required: !inbound, hint: 'IP-адреса через запятую.' },
    ] as FormField[] : []),
    ...(!inbound && !restore ? [
      { name: 'subnet', label: 'Подсеть клиентов IPv4', required: true },
      { name: 'client_email', label: 'Имя первого клиента', required: true, maxLength: 80 },
    ] as FormField[] : []),
  ];
  function submit() {
    if (wgEasy && !['true', 'false'].includes(String(values.source_ipv6))) {
      setCatalogError('Укажи режим IPv6 исходного wg-easy по результату экспорта.');
      return;
    }
    if (restore && (!selected || selected.blockers?.length)) {
      setCatalogError('Перенос остановлен: сначала устрани перечисленные несовместимости. Исходные настройки не будут заменены значениями по умолчанию.');
      return;
    }
    if (inbound) {
      const change: NonNullable<JobOptions['inbound']> = { id: inbound.id,
        expected_fingerprint: inbound.fingerprint!, operation: 'update' };
      if (values.remark !== inbound.remark) change.remark = String(values.remark);
      if (Number(values.port) !== inbound.port) change.port = Number(values.port);
      if (values.domain !== inbound.wg_domain) change.wg_domain = String(values.domain);
      if (Number(values.mtu) !== inbound.wg_mtu) change.wg_mtu = Number(values.mtu);
      if (values.dns !== inbound.wg_dns) change.wg_dns = String(values.dns);
      if (Object.keys(change).length > 3) onPreview({ inbound: change });
      return;
    }
    onPreview({ wireguard: { operation: restore ? 'restore' : 'create',
      remark: String(values.remark), domain: String(values.domain), port: Number(values.port),
      mtu: Number(values.mtu), dns: String(values.dns), subnet: String(values.subnet),
      client_email: String(values.client_email),
      ...(restore ? { source_inbound_id: Number(values.source_inbound_id),
        ...(wgEasy ? { source_ipv6: values.source_ipv6 === 'true' } : {}) } : {}),
    } }, restore ? String(values.backup_id) : undefined);
  }
  return <FormDialog title={inbound ? 'Изменить WireGuard' : 'Создать / восстановить WireGuard'}
    description={record.name} fields={fields} values={values}
    onChange={(name, value) => { setCatalogError(''); setValues(v => ({ ...v, [name]: value,
      ...(name === 'backup_id' ? { source_inbound_id: '', source_ipv6: '' } : {}),
      ...(name === 'source_inbound_id' ? { source_ipv6: '', port: String(sources.find(s => s.id === Number(value))?.port || v.port) } : {}) })); }}
    onSubmit={submit} onClose={onClose} busy={busy || loading} error={error || catalogError} submit="Посмотреть план">
    <p className="feature-hint">Ключи хранятся в БД 3x-ui. Перед изменениями создаётся SQLite-снимок. WG пакеты идут напрямую по UDP, а подписки — по HTTPS через Caddy. UFW не включает firewall провайдера.</p>
    {restore && <p className="feature-hint">Переносятся серверный ключ, клиентские ключи, PSK, адреса, keepalive, включение и сроки. MTU и DNS берутся из источника. Имеющиеся subId 3x-ui сохраняются; для wg-easy создаются новые ссылки подписок.</p>}
    {wgEasy && selected && <>
      <p className="report-warning">Старый Endpoint: {selected.endpoint?.host}:{selected.endpoint?.port}. Профили со старым IP нужно обновить на устройствах или отдельно настроить UDP-пересылку. Импорт не меняет их автоматически.</p>
      <p className="feature-hint">Исходная подсеть: {selected.subnet}; MTU: {selected.mtu}; DNS: {selected.dns || 'не задан'}. Маршрут на зарубежный выход настрой после импорта. Стандартные NAT hooks заменяет маршрутизация Xray; учётные записи админов wg-easy остаются в исходном бэкапе.</p>
      {!!selected.blockers?.length && <div role="alert" className="report-warning">
        <strong>Эти настройки нельзя перенести без изменения поведения:</strong>
        <ul>{selected.blockers.map(code => <li key={code}>{incompatibilities[code] || code}</li>)}</ul>
      </div>}
      <details><summary>Клиенты: {selected.client_count}</summary><ul>
        {selected.clients.map(client => <li key={client.email}>
          {client.name || client.email} · {client.email} · {client.enabled ? 'включён' : 'выключен'}
          {client.expiry_time ? ' · до ' + new Date(client.expiry_time).toLocaleString() : ''}
        </li>)}
      </ul></details>
    </>}
    {selected?.clients.some(c => !c.has_private_key) && <p className="report-warning">У части peers нет приватного ключа в бэкапе. Их существующие конфиги сохранят работоспособность; заново выдать такой конфиг из сервера невозможно.</p>}
  </FormDialog>;
}
