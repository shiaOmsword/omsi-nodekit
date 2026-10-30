/** Read-only system text. Parameters use named placeholders, not string concatenation. */
export const messages = {
  navigation: { nodes: 'Ноды', keys: 'SSH-ключи', help: 'Справка', label: 'Разделы панели' },
  connection: {
    title: 'Подключение и установка', installation: 'Как установлена 3x-ui', key: 'SSH-ключ для подключения',
    managed: 'Новая / управляется Nodekit', auto: 'Существующая · определить автоматически',
    native: 'Существующая · в системе', docker: 'Существующая · Docker',
    externalKey: 'Файл из ssh.identity_file', manageKeys: 'Управление ключами', help: 'Как подключиться',
    invalidYaml: 'Для выбора параметров сначала исправь YAML.',
    changed: 'Выбор перенесён в YAML. Сохрани конфигурацию перед запуском.',
    rewritten: 'Выбор пересобирает YAML и убирает комментарии. Привязка запоминается после сохранения.',
    readOnly: 'Существующая установка: обнаружение, диагностика и бэкап. Порты, TLS и Caddy читаются с сервера.',
    missingKey: 'Сохранённый ключ отсутствует — выбери другой',
  },
  keys: {
    title: 'SSH-ключи', subtitle: 'Создай ключ здесь, добавь публичную часть на VPS и выбери его у ноды.',
    create: 'Создать Ed25519', name: 'Название ключа', namePlaceholder: 'Например: Москва · основной доступ',
    generate: 'Сгенерировать ключ', empty: 'Пока нет сохранённых ключей',
    emptyBody: 'Для первого подключения создай ключ или используй свой файл в ssh.identity_file.',
    publicKey: 'Публичный ключ · authorized_keys', fingerprint: 'Fingerprint', created: 'Создан',
    use: 'Выбрать для текущей ноды', delete: 'Удалить ключ',
    deleteConfirm: 'Удалить локальную пару ключей «{name}»? Запись на VPS останется; сохранить приватную часть после удаления нельзя.',
    createdNotice: 'Ключ создан. Добавь публичную часть на VPS, затем выбери ключ у ноды.',
    deletedNotice: 'Локальный ключ удалён. При необходимости удали его публичную часть из authorized_keys на VPS.',
    storage: 'Пары находятся в backend/data/ssh-keys (или NODEKIT_DATA_DIR). Приватные ключи не выдаются через API.',
    passphrase: 'Ключ создаётся без парольной фразы для фонового SSH. Доступ к файлам ограничен текущим пользователем ОС; сохрани резервную копию каталога данных.',
    manual: 'Как добавить ключ на сервер',
  },
  report: {
    title: 'Обнаруженная конфигурация', subtitle: 'Снимок настроек ноды {node} на момент этой задачи',
    panels: 'Панели 3x-ui', caddy: 'Caddy', capabilities: 'Доступные инструменты',
    noPanels: 'Установки 3x-ui не обнаружены', noCaddy: 'Caddy не обнаружен. Для встроенного TLS панели он не обязателен.',
    selected: 'Выбрана для операции', notSelected: 'Панель не выбрана однозначно. Укажи тип установки и panel.container в YAML.',
    active: 'Работает', inactive: 'Остановлена', database: 'База данных', config: 'Конфигурация',
    network: 'Сети', mode: 'Сетевой режим', ports: 'Публикация портов', settings: 'Параметры панели',
    certificates: 'Сертификаты', panel: 'Панель', subscription: 'Подписки', key: 'Приватный ключ (путь)',
    cert: 'Сертификат (путь)', expires: 'Действует до', notBefore: 'Действует с',
    keyReadable: 'Файл ключа доступен агенту', yes: 'Да', no: 'Нет', unknown: 'Не проверено',
    empty: 'Не задано', listen: 'Слушает', hosts: 'Домены', paths: 'Пути', upstreams: 'Проксирует в',
    noRoutes: 'Маршруты не прочитаны или reverse_proxy не настроен.',
    metadataOnly: 'Статус «Срок в порядке» проверяет даты сертификата и наличие ключа. HTTPS в диагностике отдельно проверяет доверие и имя хоста; соответствие пары ключ/сертификат не проверялось.',
    defaults: 'Для отсутствующих в SQLite полей взяты стандартные значения 3x-ui; у нестандартной версии они могут отличаться: {fields}',
    fileSummary: 'Сводка Caddy взята из файла, работающий конфиг может отличаться. Для изменений понадобится отдельный план.',
    certificateStates: { not_configured: 'Встроенный TLS не настроен', missing: 'Нет сертификата / ключа',
      unknown: 'Не удалось проверить', invalid: 'Не удалось разобрать сертификат', expired: 'Срок истёк',
      not_yet_valid: 'Ещё не действует', valid: 'Срок в порядке' },
  },
  code: { copy: 'Скопировать', copied: 'Скопировано', failed: 'Автокопирование недоступно. Выдели и скопируй текст вручную.' },
  help: { title: 'Справка', subtitle: 'Подготовка, обязательные данные и первый запуск — прямо в панели.',
    contents: 'Инструкции', required: 'Обязательные данные', purpose: 'Для чего нужен Nodekit',
    open: 'Открыть справку', back: 'Вернуться к нодам' },
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
    check: { title: 'Обнаружить установку', description: '3x-ui, TLS, Caddy и сети контейнеров' },
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
