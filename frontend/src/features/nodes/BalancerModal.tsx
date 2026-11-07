import { useState } from 'react';
import type { InstallationReport, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function BalancerModal({ record, report, busy, error, onClose, onPreview }: {
  record: NodeRecord; report: InstallationReport; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const routing = report.routing;
  const members = (routing?.outbounds || []).filter(o => !['freedom', 'blackhole', 'dns'].includes(o.protocol));
  const [values, setValues] = useState<FormValues>({ tag: `ssh-${record.id}-balancer-main`, fallback_tag: routing?.outbounds.find(o => o.tag === 'direct')?.tag || '', confirm: false });
  const [validation, setValidation] = useState('');
  const fields: FormField[] = [
    { name: 'tag', label: 'Тег нового балансировщика', required: true, maxLength: 120, pattern: '[a-zA-Z0-9_.-]+' },
    ...members.map(o => ({ name: 'member-' + o.tag, label: `${o.tag} · ${o.protocol}`, type: 'checkbox' as const })),
    { name: 'fallback_tag', label: 'Fallback при отказе всех участников', type: 'select', required: true,
      options: (routing?.outbounds || []).map(o => ({ value: o.tag, label: `${o.tag} · ${o.protocol}` })) },
    { name: 'confirm', label: 'Создать roundRobin + проверку доступности и разрешить перезапуск Xray', type: 'checkbox', required: true },
  ];
  return <FormDialog title="Создать балансировщик" description={record.name} fields={fields} values={values}
    busy={busy} error={error || validation} onClose={onClose} submit="Посмотреть план"
    onChange={(name, value) => { setValidation(''); setValues(v => ({ ...v, [name]: value, ...(name !== 'confirm' ? { confirm: false } : {}) })); }}
    onSubmit={() => {
      const selected = members.filter(o => values['member-' + o.tag]).map(o => o.tag);
      if (!routing?.fingerprint || !selected.length || !values.fallback_tag || !values.confirm) {
        setValidation('Выбери выходы, fallback и подтверди изменение.'); return;
      }
      onPreview({ xray: { operation: 'balancer', expected_fingerprint: routing.fingerprint, tag: String(values.tag), members: selected, fallback_tag: String(values.fallback_tag) } });
    }}>
    <p className="feature-hint">Выбери уже подготовленные SSH-выходы. Стратегия — roundRobin. Маршруты inbound на этом шаге сохраняются. Существующие балансировщики: {(routing?.balancers || []).map(b => b.tag).join(', ') || 'не найдены'}.</p>
    <p className="report-warning">По умолчанию fallback — direct: при отказе туннелей трафик может выходить через эту VPS. Выбор blocked / blackhole блокирует такой выход.</p>
    <p className="feature-hint">Селекторы Xray работают по префиксу. Если выбор de захватывает de2, добавь оба выхода или измени их теги в 3x-ui. Неотмеченные выходы не будут добавлены молча.</p>
  </FormDialog>;
}
