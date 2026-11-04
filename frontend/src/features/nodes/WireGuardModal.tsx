import { useEffect, useState } from 'react';
import { parse } from 'yaml';
import type { Backup, InboundFinding, JobOptions, NodeRecord } from '../../types';
import { api } from '../../api';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

type Source = { id: number; remark: string; port: number; client_count: number;
  clients: { email: string; has_private_key: boolean }[] };

export function WireGuardModal({ record, inbound, backups, busy, error, onClose, onPreview }: {
  record: NodeRecord; inbound?: InboundFinding; backups: Backup[]; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions, backupId?: string) => void;
}) {
  const [values, setValues] = useState<FormValues>({ operation: 'create',
    remark: inbound?.remark || 'wg-' + record.id,
    domain: inbound?.wg_domain || parse(record.yaml)?.caddy?.domain || '',
    port: String(inbound?.port || 51820), mtu: String(inbound?.wg_mtu || 1420),
    dns: inbound ? (inbound.wg_dns || '') : '1.1.1.1', subnet: '10.77.0.0/24', client_email: 'client-wg',
    backup_id: '', source_inbound_id: '',
  });
  const [sources, setSources] = useState<Source[]>([]);
  const [catalogError, setCatalogError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true;
    setSources([]); setCatalogError(''); setLoading(false);
    if (!values.backup_id) return;
    setLoading(true);
    api<Source[]>('/backups/' + values.backup_id + '/wireguard').then(items => {
      if (!active) return;
      setSources(items);
      setValues(v => ({ ...v, source_inbound_id: items[0] ? String(items[0].id) : '',
        port: items[0] ? String(items[0].port) : v.port }));
    }).catch(() => { if (active) setCatalogError('WireGuard в этом бэкапе не прочитан. Проверь схему и ключи.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [values.backup_id]);
  const restore = !inbound && values.operation === 'restore';
  const fields: FormField[] = [
    ...(!inbound ? [{ name: 'operation', label: 'Сценарий', type: 'select', options: [
      { value: 'create', label: 'Новый inbound и клиент' }, { value: 'restore', label: 'Восстановить WG из бэкапа' },
    ] } as FormField] : []),
    ...(restore ? [
      { name: 'backup_id', label: 'Бэкап SQLite или Nodekit ZIP', type: 'select', required: true,
        options: [{ value: '', label: 'Выбери бэкап' }, ...backups.map(b => ({ value: b.id, label: b.filename }))] },
      { name: 'source_inbound_id', label: loading ? 'Чтение WG…' : 'Исходный WG inbound', type: 'select', required: true,
        options: sources.map(s => ({ value: String(s.id), label: `#${s.id} · ${s.remark} · ${s.client_count} клиентов` })) },
    ] as FormField[] : []),
    { name: 'remark', label: 'Название inbound', required: true, maxLength: 120 },
    { name: 'domain', label: 'DNS-имя WG endpoint', required: true,
      hint: 'A-запись должна указывать на VPS. WG использует UDP; HTTPS-подписка выдаётся через существующий Caddy.' },
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
      ...(restore ? { source_inbound_id: Number(values.source_inbound_id) } : {}),
    } }, restore ? String(values.backup_id) : undefined);
  }
  const selected = sources.find(s => s.id === Number(values.source_inbound_id));
  return <FormDialog title={inbound ? 'Изменить WireGuard' : 'Создать / восстановить WireGuard'}
    description={record.name} fields={fields} values={values}
    onChange={(name, value) => setValues(v => ({ ...v, [name]: value,
      ...(name === 'source_inbound_id' ? { port: String(sources.find(s => s.id === Number(value))?.port || v.port) } : {}) }))}
    onSubmit={submit} onClose={onClose} busy={busy || loading} error={error || catalogError} submit="Посмотреть план">
    <p className="feature-hint">Ключи хранятся в БД 3x-ui. Перед изменениями создаётся SQLite-снимок. WG пакеты идут напрямую по UDP, а подписки — по HTTPS через Caddy. UFW не включает firewall провайдера.</p>
    {restore && <p className="feature-hint">Переносятся серверный secretKey, клиентские ключи, PSK, адреса и существующие subId. MTU и DNS берутся из источника. Для старых конфигов нужны прежние DNS-имя и порт; после смены IP клиенту может понадобиться переподключение.</p>}
    {selected?.clients.some(c => !c.has_private_key) && <p className="report-warning">У части peers нет приватного ключа в бэкапе. Их существующие конфиги сохранят работоспособность; заново выдать такой конфиг из сервера невозможно.</p>}
  </FormDialog>;
}
