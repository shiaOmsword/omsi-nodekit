import { useState } from 'react';
import type { DiscoveryChoice, InstallationReport, NodeRecord } from '../../types';
import type { FormField, FormValues } from '../../framework/components';
import { FormDialog } from '../../framework/components';

export function DiscoveryModal({
  record,
  report,
  busy,
  error,
  onClose,
  onSave,
}: {
  record: NodeRecord;
  report: InstallationReport;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (choice: DiscoveryChoice) => void;
}) {
  const [values, setValues] = useState<FormValues>({
    panel: report.selected_panel || (report.panels.length === 1 ? report.panels[0].id : ''),
    caddy: '',
    role: 'exit',
  });
  const fields: FormField[] = report.panels.length
    ? [
        {
          name: 'panel',
          label: 'Панель 3x-ui',
          required: true,
          type: 'select',
          options: [
            { value: '', label: 'Выбери установку' },
            ...report.panels.map((p) => ({
              value: p.id,
              label: (p.container || p.service || p.id) + ' · ' + p.installation,
            })),
          ],
        },
      ]
    : [
        {
          name: 'role',
          label: 'Роль новой ноды',
          type: 'select',
          options: [
            { value: 'exit', label: 'Выходная (Европа / другие регионы)' },
            { value: 'ingress', label: 'Входная (Москва / РФ)' },
          ],
        },
        {
          name: 'caddy',
          label: 'Общий Caddy',
          type: 'select',
          options: [
            { value: '', label: 'Не подключать' },
            ...report.caddy.map((c) => ({ value: c.id, label: c.container || c.service || c.id })),
          ],
          hint: 'Если выбран Caddy, проверь домен и порты в параметрах установки.',
        },
      ];
  return (
    <FormDialog
      title="Заполнить по отчёту"
      description={record.name + ': сохранить найденные параметры подключения и установки.'}
      fields={fields}
      values={values}
      onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
      onSubmit={() =>
        onSave({
          panel_id: values.panel ? String(values.panel) : null,
          caddy_id: values.caddy ? String(values.caddy) : null,
          role: values.role as 'exit',
        })
      }
      onClose={onClose}
      busy={busy}
      error={error}
      submit="Применить и сохранить"
    />
  );
}
