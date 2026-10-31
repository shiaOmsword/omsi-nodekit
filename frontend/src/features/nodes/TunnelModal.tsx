import { useState } from 'react';
import { parse } from 'yaml';
import type { InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function TunnelModal({ record, report, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const document = parse(record.yaml);
  const tunnels: { name: string; host: string; ssh_port?: number; local_port?: number; target_port?: number }[] = document.tunnels || [];
  const panel = report.panels.find((p) => p.id === report.selected_panel);
  const inbounds = panel?.installation === 'managed'
    ? (panel.inbounds || []).filter((i) => i.enabled && i.fingerprint && i.tag) : [];
  const outbounds = (report.egress?.outbounds || []).filter((o) => o.protocol === 'vless' && !o.tag.startsWith('ssh-'));
  const [values, setValues] = useState<FormValues>({ name: tunnels[0]?.name || '', outbound_tag: outbounds[0]?.tag || '', id: String(inbounds[0]?.id || ''), confirm: false });
  const fields: FormField[] = [
    { name: 'name', label: 'SSH-туннель из YAML ноды', type: 'select', required: true,
      options: tunnels.map((t) => ({ value: t.name, label: `${t.name} · ${t.host}:${t.ssh_port || 22} · 127.0.0.1:${t.local_port || 15443} → 127.0.0.1:${t.target_port || 443}` })) },
    { name: 'outbound_tag', label: 'VLESS / RAW / REALITY outbound выходной ноды', type: 'select', required: true,
      options: outbounds.map((o) => ({ value: o.tag, label: o.tag })),
      hint: 'Создастся отдельная копия с адресом локального SSH-туннеля. UUID, SNI и ключи сохранятся.' },
    { name: 'id', label: 'Inbound Москвы, который направить через SSH', type: 'select', required: true,
      options: inbounds.map((i) => ({ value: String(i.id), label: `${i.remark || i.tag} · ${i.port} · ${i.network}` })) },
    { name: 'confirm', label: 'Применить маршрут для выбранного inbound и перезапустить Xray', type: 'checkbox', required: true },
  ];
  const ready = !!tunnels.length && !!outbounds.length && !!inbounds.length;
  return <FormDialog title="SSH-выход" description={record.name}
    fields={fields} values={values} onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
    onSubmit={() => {
      const inbound = inbounds.find((i) => i.id === Number(values.id));
      if (ready && inbound && values.confirm) onPreview({ tunnel: { name: String(values.name), outbound_tag: String(values.outbound_tag), id: inbound.id, expected_fingerprint: inbound.fingerprint! } });
    }} onClose={onClose} busy={busy} error={error} submit="Посмотреть план">
    {!ready && <p className="report-warning">Добавь tunnels в YAML ноды и VLESS / RAW / REALITY outbound в 3x-ui, затем обнови обнаружение. Выходной inbound должен быть доступен по 127.0.0.1 на выходной ноде.</p>}
    <p>Приватный SSH-ключ и проверенный known_hosts должны находиться на московской VPS по путям из tunnels. Ключ должен работать без ввода пароля. Доступ к выходной ноде проверяется с VPS.</p>
    <p>Перед изменением сохраняется приватный бэкап. Проверка получает HTTPS-ответ через выходной inbound. При ошибке выполняется откат; участок телефон → Москва этим тестом не проверяется.</p>
  </FormDialog>;
}
