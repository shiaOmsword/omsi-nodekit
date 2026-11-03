import type { Action, Job, JobDetail } from '../types';

export const actionLabels: Record<Action, { title: string; description: string }> = {
  attach_caddy: { title: 'Подключить Caddy', description: 'Подключить выбранный Caddy к установленной панели и подготовить подписки и XHTTP.' },
  system_backup: { title: 'Бэкап ноды', description: 'БД, TCP-настройки, ключи SSH-туннелей и конфигурация Nodekit для восстановления.' },
  system_restore: { title: 'Восстановить настройки ноды', description: 'Вернуть TCP-настройки и ключи туннелей из архива до развёртывания панели.' },
  network_benchmark: { title: 'Замеры сети', description: 'Прямой HTTPS с VPS, DNS, ICMP и общие TCP-счётчики с заданными порогами.' },
  tcp_tuning: { title: "TCP / BBR", description: "Проверить и сохранить TCP congestion control на VPS. Действующие SSH-сессии не перезапускаются." },
  subscription_maintenance: { title: 'Обслуживание подписок', description: 'Проверить публичный HTTPS/DNS или вручную перезапустить только управляемую 3x-ui для очистки серверного кэша.' },
  client_import: { title: 'Клиенты из бэкапа', description: 'Выборочно восстановить VLESS-клиентов, не меняя их UUID и ID подписки.' },
  xhttp: { title: 'VLESS / XHTTP', description: 'Приватный XHTTP inbound, публичный HTTPS в Caddy и scoped UFW.' },
  tunnel: { title: 'SSH-выход', description: 'Создать SSH-туннель и направить выбранный inbound через выходную ноду.' },
  inbound: { title: 'Изменение inbound', description: 'Порт, SNI, название и правила UFW выбранного inbound.' },
  traffic: { title: 'Проверка трафика', description: 'Сравнить прямой HTTPS с реальным VLESS/REALITY-подключением через inbound.' },
  check: { title: 'Обнаружение', description: 'Найти 3x-ui, Caddy и настройки сервера.' },
  doctor: { title: 'Диагностика', description: 'Проверить панель, сертификаты и туннели.' },
  fresh: { title: 'Новая установка', description: 'Развернуть 3x-ui на подготовленном сервере.' },
  restore: {
    title: 'Восстановление',
    description: 'Восстановить панель и клиентов из базы SQLite.',
  },
  backup: { title: 'Создание бэкапа', description: 'Сохранить согласованный снимок базы 3x-ui.' },
  configure: { title: 'Подписки и inbound', description: 'Применить домен и порт подписок, создать недостающие inbound с первым клиентом.' },
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
