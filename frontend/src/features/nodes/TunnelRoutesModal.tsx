import { useState } from 'react';
import type { InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function TunnelRoutesModal({ record, report, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const routing = report.routing;
  const panel = report.panels.find(p => p.id === report.selected_panel);
  const inbounds = panel?.installation === 'managed' ? panel.inbounds || [] : [];
  const editable = (routing?.rules || []).filter(r => r.editable);
  function initial(index: string): FormValues {
    const rule = editable.find(r => String(r.index) === index);
    return { rule: index, balancer: rule?.balancer_tag || routing?.balancers[0]?.tag || '', confirm: false,
      ...Object.fromEntries(inbounds.map(i => ['inbound-' + i.id, !!i.tag && !!rule?.inbound_tags.includes(i.tag)])) };
  }
  const [values, setValues] = useState<FormValues>(() => initial(editable[0] ? String(editable[0].index) : 'new'));
  const [validation, setValidation] = useState('');
  const rule = editable.find(r => String(r.index) === values.rule);
  const missing = rule?.inbound_tags.filter(tag => !inbounds.some(i => i.tag === tag)) || [];
  const fields: FormField[] = [
    { name: 'rule', label: 'Маршрут', type: 'select', required: true,
      options: [{ value: 'new', label: 'Создать новое правило' }, ...editable.map(r => ({ value: String(r.index),
        label: `#${r.index + 1} · ${r.inbound_tags.join(', ')} → ${r.balancer_tag || r.outbound_tag}` }))] },
    { name: 'balancer', label: 'Балансировщик Xray', type: 'select', required: true,
      options: (routing?.balancers || []).map(b => ({ value: b.tag, label: `${b.tag} · ${b.strategy} · fallback ${b.fallback_tag || 'не задан'}` })) },
    ...inbounds.map(i => ({ name: 'inbound-' + i.id, type: 'checkbox' as const,
      label: `${i.remark || i.tag || '#' + i.id} · ${i.protocol.toUpperCase()} · ${i.port}${i.enabled ? '' : ' · выключен'}`,
      hint: !i.enabled || !i.tag || !i.fingerprint ? 'Для выбора включи inbound и обнови обнаружение.' : undefined })),
    { name: 'confirm', type: 'checkbox', required: true,
      label: 'Сохранить весь выбранный список inbound и разрешить перезапуск Xray',
      hint: 'Снятые inbound будут использовать другие правила, включая direct, если он настроен. Порядок остальных правил сохраняется.' },
  ];
  return <FormDialog title="Настроить маршрут" description={record.name} fields={fields} values={values}
    busy={busy} error={error || validation} onClose={onClose} submit="Посмотреть план"
    onChange={(name, value) => {
      setValidation('');
      if (name === 'rule') setValues(initial(String(value)));
      else setValues(v => ({ ...v, [name]: value, ...(name !== 'confirm' ? { confirm: false } : {}) }));
    }} onSubmit={() => {
      const selected = inbounds.filter(i => values['inbound-' + i.id]);
      if (!routing?.fingerprint || !values.balancer || !values.confirm || !selected.length || selected.some(i => !i.enabled || !i.tag || !i.fingerprint)) {
        setValidation('Выбери балансировщик, хотя бы один включённый inbound и подтверди изменение.'); return;
      }
      onPreview({ xray: { operation: 'route', expected_fingerprint: routing.fingerprint, balancer_tag: String(values.balancer),
        ...(rule ? { rule_index: rule.index } : {}), inbounds: selected.map(i => ({ id: i.id, expected_fingerprint: i.fingerprint! })) } });
    }}>
    {!routing?.balancers.length && <p className="report-warning">Сначала создай балансировщик и обнови обнаружение. Балансировщики, созданные вручную в 3x-ui, также доступны.</p>}
    {!!missing.length && <p className="report-warning">В старом правиле есть отсутствующие inbound: {missing.join(', ')}. При сохранении они будут убраны из выбранного правила.</p>}
    <p className="feature-hint">Отметь WG и VLESS, выбери общий балансировщик. Для существующего inbound выбери его правило, чтобы сохранить приоритет. Новое правило добавляется в конец; пересекающиеся полные маршруты нужно изменить явно.</p>
    <p className="feature-hint">Условные, выключенные и API-правила здесь доступны для просмотра в таблице. Проверяется сохранённая и запущенная конфигурация Xray; клиентский WG/UDP-трафик проверяется отдельно.</p>
  </FormDialog>;
}
