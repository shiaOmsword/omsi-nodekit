/** Read-only system text. Parameters use named placeholders, not string concatenation. */
export const messages = {
  error: {
    invalidResponse: 'Сервер вернул неожиданный формат ответа',
    network: 'Не удалось связаться с сервером',
    unknown: 'Произошла неизвестная ошибка',
    http: 'HTTP {status}',
    close: 'Закрыть ошибку',
  },
  notice: {
    configSaved: 'Конфигурация проверена и сохранена',
    jobStarted: 'Задача запущена. Ход выполнения — в журнале ниже.',
    backupImported: 'Снимок SQLite проверен и добавлен',
  },
  confirm: {
    discardForNode: 'Перейти к другой ноде и отменить несохранённые изменения?',
    discardForNew: 'Создать ноду и отменить несохранённые изменения?',
  },
  status: {
    queued: 'В очереди', running: 'Выполняется', succeeded: 'Готово',
    failed: 'Ошибка', interrupted: 'Прервано', unknown: 'Неизвестный статус',
  },
  action: {
    check: { title: 'Проверить окружение', description: 'SSH, Docker, Compose и systemd' },
    fresh: { title: 'Развернуть с нуля', description: 'Новая пустая панель и туннели' },
    restore: { title: 'Восстановить из БД', description: 'Сохранить клиентов, ключи и маршруты' },
    doctor: { title: 'Диагностика', description: 'Панель, туннели и тест трафика' },
    backup: { title: 'Скачать бэкап', description: 'Согласованный снимок SQLite' },
  },
  ui: {
    newNode: 'Новая нода', newNodeHelp: 'Начни с YAML-конфигурации', addNode: 'Добавить ноду',
    nodes: 'Ноды', myNodes: 'МОИ НОДЫ', workspace: 'ЛОКАЛЬНОЕ ПРОСТРАНСТВО',
    emptyNodesTitle: 'Добавь первую ноду.', emptyNodesBody: 'Её настройки останутся здесь.',
    localControlTitle: 'Всё под твоим контролем', localControlBody: 'Локальная панель.',
    sshConnection: 'Подключение к VPS по SSH.', online: 'Backend подключён', offline: 'Нет связи с backend',
    infrastructure: 'Инфраструктура', localWorkspace: 'LOCAL WORKSPACE',
    slogan: 'МЕНЬШЕ РУТИНЫ. БОЛЬШЕ КОНТРОЛЯ.', title: 'Твои ноды. Один пульт.',
    subtitle: 'Разворачивай, восстанавливай и проверяй — по одному конфигу.',
    statistics: 'Статистика', nodeCount: 'Нод в конфигурации', activeJobs: 'Активных задач',
    backupCount: 'Снимков базы', completedJobs: 'Успешных задач*',
    unsaved: 'Не сохранено', saved: 'Сохранено', save: 'Сохранить',
    planFiles: 'Файлы плана', yamlLabel: 'YAML конфигурация ноды',
    validationHint: 'Конфиг проверяется перед сохранением',
    operations: 'Операции', operationsHint: 'Выбери следующий шаг',
    restoreBackup: 'Снимок для восстановления', selectBackup: 'Выбери .db файл',
    uploadBackup: 'Загрузить SQLite .db', saveFirst: 'Сначала сохрани конфигурацию.',
    previewHint: 'Перед запуском покажем план и файлы.', preview: 'Показать план',
    previewTitle: 'ПРЕДВАРИТЕЛЬНЫЙ ПЛАН', closePlan: 'Закрыть план',
    deploymentHint: 'Только новая нода и пустой каталог. Клиенты и маршруты восстанавливаются из БД; чистая панель будет пустой. Внешние сертификаты и SSH-ключи подготовь отдельно.',
    inspectFiles: 'Посмотреть создаваемые файлы', launch: 'Запустить {action}',
    journal: 'Журнал операций', journalHint: 'Реальный вывод задач, без догадок',
    running: 'ВЫПОЛНЯЕТСЯ', idle: 'ОЖИДАНИЕ', emptyJobs: 'Пока без задач',
    emptyJobsHint: 'Начни с проверки окружения', taskJournal: 'Журнал задачи',
    terminalReady: 'nodekit — ready', waitForVps: 'Ожидаем ответ VPS…',
    downloadBackup: 'Скачать снимок БД', terminalEmpty: 'Здесь появится ход выполнения.',
    terminalHint: 'Выбери операцию и запусти её из панели.', backups: 'Бэкапы SQLite',
    backupSize: '{size} КБ', footer: 'СДЕЛАНО ДЛЯ СПОКОЙНЫХ ВЕЧЕРОВ',
    trafficHint: '* По журналу задач · Статус VPN требует проверки трафика',
  },
} as const;

export function formatMessage(template: string, parameters: Record<string, string | number>): string {
  const names = [...template.matchAll(/\{(\w+)\}/g)].map(match => match[1]);
  if (new Set(names).size !== Object.keys(parameters).length || names.some(name => !Object.hasOwn(parameters, name))) {
    throw new TypeError('message_parameters_mismatch');
  }
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(parameters[name]));
}

export function statusLabel(status: string): string {
  return Object.hasOwn(messages.status, status)
    ? messages.status[status as keyof typeof messages.status]
    : messages.status.unknown;
}
