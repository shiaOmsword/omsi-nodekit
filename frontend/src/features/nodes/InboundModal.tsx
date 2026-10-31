import { useState } from 'react';
import type { InboundFinding, JobOptions, NodeRecord } from '../../types';
import { FormDialog } from '../../framework/components';
import type { FormField, FormValues } from '../../framework/components';

export function InboundModal({ record, inbound, remove, busy, error, onClose, onPreview }: {
  record: NodeRecord; inbound: InboundFinding; remove: boolean; busy: boolean; error: string;
  onClose: () => void; onPreview: (options: JobOptions) => void;
}) {
  const originalSni = inbound.server_names?.[0] || '';
  const [values, setValues] = useState<FormValues>({ remark: inbound.remark, port: String(inbound.port),
    server_name: originalSni, close_unmanaged_rule: false, confirm: false });
  const fields: FormField[] = remove ? [
    { name: 'confirm', label: 'Удалить inbound и всех его клиентов', type: 'checkbox', required: true },
  ] : [
    { name: 'remark', label: 'Название inbound', required: true, maxLength: 120 },
    { name: 'port', label: 'Порт inbound', type: 'number', required: true, min: 1, max: 65535 },
    ...(inbound.security === 'reality' ? [{ name: 'server_name', label: 'REALITY SNI', required: true,
      hint: 'Обновятся SNI и адрес REALITY target с прежним target-портом. Ключи и клиенты сохранятся.' } as FormField] : []),
  ];
  fields.push({ name: 'close_unmanaged_rule', label: 'Удалить старое ручное разрешение UFW этого TCP-порта', type: 'checkbox',
    hint: 'Только точное правило для старого порта, если он больше не используется. Общие правила, диапазоны и порты других сервисов сохраняются. Правила Nodekit согласуются автоматически.' });
  function submit() {
    const change: NonNullable<JobOptions['inbound']> = { id: inbound.id,
      expected_fingerprint: inbound.fingerprint!, operation: remove ? 'delete' : 'update',
      close_unmanaged_rule: !!values.close_unmanaged_rule };
    if (!remove) {
      if (values.remark !== inbound.remark) change.remark = String(values.remark);
      if (Number(values.port) !== inbound.port) change.port = Number(values.port);
      if (values.server_name !== originalSni) change.server_name = String(values.server_name);
      if (!change.remark && !change.port && !change.server_name) return;
    }
    onPreview({ inbound: change });
  }
  return <FormDialog title={remove ? 'Удалить inbound' : 'Изменить inbound'}
    description={`${record.name} · #${inbound.id} · ${inbound.remark || inbound.protocol}`}
    fields={fields} values={values} onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
    onSubmit={submit} onClose={onClose} busy={busy} error={error} submit="Посмотреть план">
    <div className="form-section"><p>{remove
      ? `Будут удалены inbound и его клиенты (${inbound.client_count}). Перед операцией сохранится приватный SQLite snapshot на VPS.`
      : 'Изменения применяются через API панели. UUID, ID подписок, клиентские настройки и ключи REALITY сохраняются.'}</p>
      <p className="feature-hint">Xray может кратковременно перезапуститься. После смены порта/SNI обнови подписку в клиентах. Здесь подготавливается только план; запуск — следующим подтверждением.</p></div>
  </FormDialog>;
}
