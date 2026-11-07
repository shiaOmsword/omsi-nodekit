import { useState } from 'react';
import { parse } from 'yaml';
import type { InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export interface TunnelModalProps {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}

export function TunnelModal({ record, report, busy, error, onClose, onPreview, pool = false }: TunnelModalProps & { pool?: boolean }) {
  const tunnels: { name: string; host: string; ssh_port?: number; local_port?: number; target_port?: number }[] = parse(record.yaml)?.tunnels || [];
  const routing = report.routing;
  const outbounds = (routing?.outbounds || []).filter(o => o.protocol === 'vless');
  const [values, setValues] = useState<FormValues>({
    name: tunnels[0]?.name || '', outbound_tag: outbounds.find(o => !o.tag.startsWith('ssh-'))?.tag || outbounds[0]?.tag || '',
    balancer_tag: `ssh-${record.id}-balancer-main`, fallback_tag: routing?.outbounds.find(o => o.tag === 'direct')?.tag || '', confirm: false,
    ...Object.fromEntries(tunnels.map((t, i) => ['member-' + t.name, i < 6])),
  });
  const [validation, setValidation] = useState('');
  const fields: FormField[] = [
    ...(pool ? tunnels.map(t => ({ name: 'member-' + t.name, label: `${t.name} · ${t.host}:${t.ssh_port ?? report.tunnels?.find(live => live.name === t.name)?.ssh_port ?? '?'} · 127.0.0.1:${t.local_port ?? report.tunnels?.find(live => live.name === t.name)?.local_port ?? '?'} → 127.0.0.1:${t.target_port ?? report.tunnels?.find(live => live.name === t.name)?.target_port ?? '?'}`, type: 'checkbox' as const })) : [
      { name: 'name', label: 'SSH-туннель из YAML', type: 'select' as const, required: true,
        options: tunnels.map(t => ({ value: t.name, label: `${t.name} · ${t.host}:${t.ssh_port ?? report.tunnels?.find(live => live.name === t.name)?.ssh_port ?? '?'} · 127.0.0.1:${t.local_port ?? report.tunnels?.find(live => live.name === t.name)?.local_port ?? '?'} → 127.0.0.1:${t.target_port ?? report.tunnels?.find(live => live.name === t.name)?.target_port ?? '?'}` })) },
    ]),
    { name: 'outbound_tag', label: 'Образец VLESS / RAW / REALITY для новых выходов', type: 'select', required: true,
      options: outbounds.map(o => ({ value: o.tag, label: o.tag })),
      hint: 'Новые копии сохранят UUID, SNI и ключи образца. Уже созданные выходы сохранят свои параметры. Для разных выходных VLESS endpoint подготовь туннели по одному.' },
    ...(pool ? [
      { name: 'balancer_tag', label: 'Тег балансировщика roundRobin', required: true, maxLength: 120, pattern: '[a-zA-Z0-9_.-]+' },
      { name: 'fallback_tag', label: 'Fallback при отказе всех выходов', type: 'select' as const, required: true,
        options: (routing?.outbounds || []).filter(o => o.protocol === 'freedom' || o.protocol === 'blackhole').map(o => ({ value: o.tag, label: `${o.tag} · ${o.protocol}` })) },
    ] : []),
    { name: 'confirm', label: 'Разрешить запуск служб и перезапуск Xray для новых ресурсов', type: 'checkbox', required: true },
  ];
  function submit() {
    const names = pool ? tunnels.filter(t => values['member-' + t.name]).map(t => t.name) : [String(values.name)];
    if (!values.confirm || !routing?.fingerprint || !names.length || names.length > 6 || !values.outbound_tag || (pool && !values.fallback_tag)) {
      setValidation('Нужны актуальное обнаружение Xray, образец outbound и от 1 до 6 туннелей. Подтверди изменение.'); return;
    }
    onPreview({ tunnel_setup: { names, outbound_tag: String(values.outbound_tag), expected_fingerprint: routing.fingerprint,
      ...(pool ? { balancer_tag: String(values.balancer_tag), fallback_tag: String(values.fallback_tag) } : {}) } });
  }
  return <FormDialog title={pool ? 'Поднять SSH-пул' : 'Подготовить SSH-туннель'} description={record.name}
    fields={fields} values={values} busy={busy} error={error || validation} onClose={onClose} onSubmit={submit} submit="Посмотреть план"
    onChange={(name, value) => { setValidation(''); setValues(v => ({ ...v, [name]: value, ...(name !== 'confirm' ? { confirm: false } : {}) })); }}>
    {!routing?.readable && <p className="report-warning">Обнови обнаружение: нужен сохранённый шаблон Xray управляемой панели.</p>}
    <p className="feature-hint">Сначала подготавливаются SSH-службы и копии VLESS outbound с локальными адресами. Существующие маршруты сохраняются. {pool ? 'Создаётся балансировщик из выбранных выходов; совпадающие ресурсы используются повторно.' : 'Затем можно создать балансировщик и выбрать inbound в настройке маршрута.'}</p>
    {pool && <p className="report-warning">Fallback direct разрешает выход через эту VPS (например, Москву), если все туннели недоступны. Для блокировки выбери blackhole.</p>}
    <p className="feature-hint">Ключ без пароля и known_hosts должны находиться на VPS по путям из YAML. Проверяется HTTPS через каждый выход; участок телефон → Москва, WG и клиентский UDP проверяются отдельно.</p>
  </FormDialog>;
}
