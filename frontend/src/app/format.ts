import type { Action, Job, JobDetail } from '../types';

export const actionLabels: Record<Action, { title: string; description: string }> = {
  check: { title: 'Обнаружение', description: 'Найти 3x-ui, Caddy и настройки сервера.' },
  doctor: { title: 'Диагностика', description: 'Проверить панель, сертификаты и туннели.' },
  fresh: { title: 'Новая установка', description: 'Развернуть 3x-ui на подготовленном сервере.' },
  restore: {
    title: 'Восстановление',
    description: 'Восстановить панель и клиентов из базы SQLite.',
  },
  backup: { title: 'Создание бэкапа', description: 'Сохранить согласованный снимок базы 3x-ui.' },
};
export const isRunning = (job: Job) => ['queued', 'running'].includes(job.status);
export function timestamp(value: string) {
  const normalized = value.replace(' ', 'T');
  return new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(normalized) ? normalized : normalized + 'Z');
}
export function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = timestamp(value);
  return Number.isNaN(date.valueOf())
    ? '—'
    : new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      }).format(date);
}
export function formatBytes(size: number) {
  return size >= 1024 * 1024
    ? (size / 1024 / 1024).toFixed(1) + ' МБ'
    : Math.max(1, Math.round(size / 1024)) + ' КБ';
}
export function downloadLog(job: JobDetail) {
  const text =
    [
      'Node: ' + job.node_id,
      'Job: ' + job.id,
      'Action: ' + job.action,
      'Status: ' + job.status,
      ...(job.error ? ['Error: ' + job.error] : []),
      ...job.events.map((e) => '[' + e.created_at + '] [' + e.level + '] ' + e.message),
    ].join('\n') + '\n';
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'nodekit-' + job.node_id + '-' + job.id + '.log';
  link.click();
  URL.revokeObjectURL(url);
}
