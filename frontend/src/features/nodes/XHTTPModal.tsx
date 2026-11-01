import { useState } from 'react';
import { parse } from 'yaml';
import type { InboundFinding, InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function XHTTPModal({ record, report, inbound, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; inbound?: InboundFinding;
  busy: boolean; error: string; onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const config = parse(record.yaml);
  const isEditing = !!inbound;
  const domain = String(inbound?.xhttp_domain || ('vpn.' + String(config.caddy?.domain || 'example.com')));
  const occupied = new Set(report.panels.flatMap((p) => (p.inbounds || []).map((i) => i.port)));
  const port = inbound?.port || [10080, 10081, 10082, 10083].find((p) => !occupied.has(p)) || 11080;
  const publishOnly = !!inbound && !inbound.xhttp_domain;
  const [values, setValues] = useState<FormValues>({
    remark: inbound?.remark || 'xhttp-' + record.id,
    domain, port: String(port),
    path: inbound?.xhttp_path || '/xhttp-' + record.id + '/',
    mode: inbound?.xhttp_mode || 'auto',
    client_email: '', confirm: false,
  });
  const fields: FormField[] = [
    { name: 'remark', label: 'Название inbound', required: true, maxLength: 120 },
    { name: 'domain', label: 'Публичный HTTPS-домен', required: true,
      hint: 'Должен указывать на VPS. Не может совпадать с чужим сайтом или доменом подписок.' },
    { name: 'port', label: 'Приватный порт Xray', type: 'number', min: 1, max: 65535, required: true,
      hint: 'Слушается только на адресе backend Caddy; наружу не публикуется.' },
    { name: 'path', label: 'Путь XHTTP', required: true, pattern: '/[a-zA-Z0-9_-]{1,64}/',
      hint: 'Путь в клиентском профиле и Caddy должен быть одинаковым; например /xhttp-ultra/.' },
    { name: 'mode', label: 'Режим XHTTP', type: 'select', required: true,
      options: [{ value: 'auto', label: 'auto' }, { value: 'packet-up', label: 'packet-up' },
        { value: 'stream-up', label: 'stream-up' }] },
    ...(!isEditing ? [{ name: 'client_email', label: 'Имя первого клиента',
      hint: 'Необязательно. UUID и subId создадутся на VPS.' } as FormField] : []),
    { name: 'confirm', label: 'Применить изменения только к своей панели и управляемому Caddy site',
      type: 'checkbox', required: true },
  ];
  function submit() {
    if (!values.confirm) return;
    const change: NonNullable<JobOptions['xhttp']> = {
      operation: publishOnly ? 'publish' : isEditing ? 'update' : 'create',
      remark: String(values.remark).trim(),
      domain: String(values.domain).trim(),
      port: Number(values.port),
      path: String(values.path),
      mode: values.mode as 'auto' | 'packet-up' | 'stream-up',
    };
    if (isEditing) {
      change.id = inbound.id;
      change.expected_fingerprint = inbound.fingerprint;
    } else if (String(values.client_email).trim()) {
      change.client_email = String(values.client_email).trim();
    }
    onPreview({ xhttp: change });
  }
  return <FormDialog title={publishOnly ? 'Опубликовать XHTTP в подписке' : isEditing ? 'Изменить VLESS / XHTTP' : 'Создать VLESS / XHTTP'}
    description={record.name + ' · Caddy HTTPS → Xray h2c'}
    fields={fields} values={values} onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
    onSubmit={submit} onClose={onClose} busy={busy} error={error} submit="Посмотреть план">
    {publishOnly && <p className="feature-hint">Публикация существующего inbound в Hosts 3x-ui. Caddy и Xray не меняются. Домен уже должен принимать HTTPS.</p>}
    <p className="feature-hint">Caddy принимает TLS на публичном 443, XHTTP backend работает без TLS. Будут проверены существующие маршруты, SQLite-снимок и UFW. Docker и чужие Caddy сайты не изменятся.</p>
    <p className="feature-hint">Профиль телефона: VLESS / XHTTP / TLS, порт 443, ALPN h2, SNI = домен, путь из формы, flow пустой. После операции проверь Hosts override в 3x-ui для подписок.</p>
    {isEditing && <p className="feature-hint">Редактируются только XHTTP inbound, созданные Nodekit; вручную созданные маршруты не перезаписываются.</p>}
  </FormDialog>;
}
