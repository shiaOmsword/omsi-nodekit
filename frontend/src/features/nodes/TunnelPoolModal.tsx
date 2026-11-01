import { useState } from 'react';
import { parse } from 'yaml';
import type { InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function TunnelPoolModal({ record, report, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const tunnels: { name: string; host: string; local_port: number; target_port: number }[] = parse(record.yaml)?.tunnels || [];
  const panel = report.panels.find((p) => p.id === report.selected_panel);
  const inbounds = panel?.installation === 'managed'
    ? (panel.inbounds || []).filter((i) => i.enabled && i.fingerprint && i.tag) : [];
  const outbounds = (report.egress?.outbounds || []).filter((o) => o.protocol === 'vless' && !o.tag.startsWith('ssh-'));
  const [values, setValues] = useState<FormValues>({
    pool_name: (tunnels[0]?.name || 'exit') + '-pool',
    members: tunnels.map((t) => t.name).join(', '),
    outbound_tag: outbounds[0]?.tag || '',
    id: String(inbounds[0]?.id || ''),
    confirm: false,
  });
  const fields: FormField[] = [
    { name: 'pool_name', label: 'Имя пула', required: true, pattern: '[a-z][a-z0-9-]{0,39}' },
    { name: 'members', label: 'Имена SSH-туннелей из YAML, через запятую', required: true,
      hint: 'Каждый YAML туннель запускается отдельной systemd-службой и слушает собственный local_port.' },
    { name: 'outbound_tag', label: 'Исходный VLESS / RAW / REALITY outbound', type: 'select', required: true,
      options: outbounds.map((o) => ({ value: o.tag, label: o.tag })) },
    { name: 'id', label: 'Inbound Москвы', type: 'select', required: true,
      options: inbounds.map((i) => ({ value: String(i.id), label: i.remark + ' · ' + i.network })) },
    { name: 'confirm', label: 'Разрешаю перезапуск Xray и установку всех SSH-служб пула', type: 'checkbox', required: true },
  ];
  function submit() {
    const names = String(values.members).split(',').map((n) => n.trim()).filter(Boolean);
    const inbound = inbounds.find((i) => i.id === Number(values.id));
    if (!values.confirm || !inbound || names.length < 2 || new Set(names).size !== names.length) return;
    if (names.some((name) => !tunnels.some((t) => t.name === name))) return;
    onPreview({ tunnel: { name: names[0], members: names, pool_name: String(values.pool_name),
      id: inbound.id, expected_fingerprint: inbound.fingerprint!, outbound_tag: String(values.outbound_tag) } });
  }
  return <FormDialog title="SSH-пул" description={record.name + ' · отдельные OpenSSH TCP-сессии'}
    fields={fields} values={values} onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
    onSubmit={submit} onClose={onClose} busy={busy} error={error} submit="Посмотреть план">
    <p className="feature-hint">Пул поддерживает один и тот же выходной VLESS endpoint, но несколько SSH-сессий. Перед маршрутами проверяются ключи, systemd и HTTPS через каждый путь. Существующие одиночные SSH-маршруты участников могут быть перенесены в пул только при совпадении ownership, outbound, inbound и настроек.</p>
    <p className="feature-hint">Xray создаёт roundRobin + observatory. При отказе всех путей fallback указывает на blocked, а не direct. Никакие чужие systemd units не перезаписываются.</p>
  </FormDialog>;
}
