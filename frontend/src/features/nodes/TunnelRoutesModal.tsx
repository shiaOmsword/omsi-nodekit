import { useState } from 'react';
import type { InstallationReport, JobOptions, NodeRecord, SSHExitFinding } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

function initialValues(exit?: SSHExitFinding): FormValues {
  return { exit: exit ? exit.kind + ':' + exit.name : '', confirm: false,
    ...Object.fromEntries((exit?.inbound_ids || []).map(id => ['inbound-' + id, true])) };
}

export function TunnelRoutesModal({ record, report, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const exits = report.ssh_exits || [];
  const panel = report.panels.find(p => p.id === report.selected_panel);
  const inbounds = panel?.installation === 'managed' ? panel.inbounds || [] : [];
  const [values, setValues] = useState<FormValues>(() => initialValues(exits[0]));
  const [validation, setValidation] = useState('');
  const exit = exits.find(e => e.kind + ':' + e.name === values.exit);
  const ids = [...new Set([...(exit?.inbound_ids || []),
    ...inbounds.filter(i => i.enabled && i.tag && i.fingerprint).map(i => i.id)])];
  const fields: FormField[] = [
    { name: 'exit', label: 'Установленный SSH-выход', type: 'select', required: true,
      options: exits.map(e => ({ value: e.kind + ':' + e.name,
        label: (e.kind === 'pool' ? 'Пул ' : 'Туннель ') + e.name })) },
    ...ids.map(id => {
      const inbound = inbounds.find(i => i.id === id);
      return { name: 'inbound-' + id, type: 'checkbox' as const,
        label: inbound ? `${inbound.remark || 'Inbound #' + id} · ${inbound.protocol.toUpperCase()} · ${inbound.port}${inbound.enabled ? '' : ' · выключен'}` : `Inbound #${id} · отсутствует в отчёте`,
        hint: !inbound?.enabled || !inbound?.tag || !inbound?.fingerprint ? 'Сними отметку или обнови обнаружение после включения inbound.' : undefined };
    }),
    { name: 'confirm', type: 'checkbox', required: true,
      label: 'Применить весь выбранный список и разрешить перезапуск Xray',
      hint: 'Снятые inbound будут использовать остальные правила маршрутизации, включая direct, если он настроен.' },
  ];
  function submit() {
    const selected = ids.filter(id => values['inbound-' + id]).map(id => inbounds.find(i => i.id === id));
    if (!exit || !values.confirm || !selected.length || selected.some(i => !i?.enabled || !i.tag || !i.fingerprint)) {
      setValidation('Выбери хотя бы один включённый inbound из актуального отчёта и подтверди изменение.');
      return;
    }
    onPreview({ tunnel_route: { kind: exit.kind, name: exit.name,
      expected_exit_fingerprint: exit.fingerprint,
      inbounds: selected.map(i => ({ id: i!.id, expected_fingerprint: i!.fingerprint! })) } });
  }
  return <FormDialog title="Inbound общего SSH-выхода" description={record.name}
    fields={fields} values={values} busy={busy} error={error || validation}
    onChange={(name, value) => {
      setValidation('');
      if (name === 'exit') setValues(initialValues(exits.find(e => e.kind + ':' + e.name === value)));
      else setValues(v => ({ ...v, [name]: value, ...(name !== 'confirm' ? { confirm: false } : {}) }));
    }} onSubmit={submit} onClose={onClose} submit="Посмотреть план">
    {!exits.length && <p className="report-warning">Нужен установленный SSH-выход Nodekit и актуальное обнаружение его маршрута.</p>}
    <p className="feature-hint">Отметь все inbound, которые должны использовать этот выход: например, VLESS и WireGuard. Сохрани отметку VLESS, чтобы добавить WG к нему. SSH-службы и ключи сохраняются; изменяется список inbound одного маршрута. Трафик может кратковременно прерваться при перезапуске Xray.</p>
    <p className="feature-hint">Проверяется HTTPS через существующий выход. Подключение телефона по WG и UDP-трафик проверяются отдельно.</p>
  </FormDialog>;
}
