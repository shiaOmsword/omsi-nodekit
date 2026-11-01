import { useState } from 'react';
import { Play, RefreshCw } from 'lucide-react';
import type { Action, NodeRecord, Plan } from '../../types';
import { Alert, Button, Loading, Modal } from '../../framework/components';
import { actionLabels } from '../../app/format';

export function PlanModal({
  record,
  action,
  plan,
  busy,
  error,
  onClose,
  onReload,
  onLaunch,
}: {
  record: NodeRecord;
  action: Action;
  plan: Plan | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onReload: () => void;
  onLaunch: () => void;
}) {
  const [tab, setTab] = useState<'steps' | 'files'>('steps');
  const [file, setFile] = useState('');
  const files = Object.keys(plan?.files || {});
  return (
    <Modal
      title={(plan?.options?.inbound?.operation === 'delete' ? 'Удаление inbound' : actionLabels[action].title) + ': план'}
      description={record.name}
      wide
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button onClick={onReload} disabled={busy} icon={<RefreshCw size={16} />}>
            Обновить план
          </Button>
          <Button
            className={plan?.options?.inbound?.operation === 'delete' ? 'danger-button' : ''}
            variant="primary"
            onClick={onLaunch}
            disabled={!plan}
            loading={busy}
            icon={<Play size={16} />}
          >
            {plan?.options?.inbound?.operation === 'delete' ? 'Удалить inbound' : plan?.options?.subscription_maintenance?.mode === 'clear_server_cache' ? 'Перезапустить 3x-ui' : 'Запустить операцию'}
          </Button>
        </>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      {!plan && busy ? (
        <Loading label="Подготовка плана…" />
      ) : (
        plan && (
          <>
            <div className="plan-context">
              <span
                className={'tag ' + (['fresh', 'restore', 'configure', 'inbound', 'tunnel', 'xhttp', 'client_import', 'subscription_maintenance', 'tcp_tuning'].includes(action) ? 'tag-warning' : '')}
              >
                {['fresh', 'restore', 'configure', 'inbound', 'tunnel', 'xhttp', 'tcp_tuning'].includes(action) || (action === 'subscription_maintenance' && plan.options?.subscription_maintenance?.mode === 'clear_server_cache')
                  ? 'Изменяет сервер'
                  : 'Сервисы на VPS не изменяются'}
              </span>
              <code>{plan.remote_dir}</code>
            </div>
            <div className="page-tabs" role="group" aria-label="Содержимое плана">
              <button
                aria-pressed={tab === 'steps'}
                className={tab === 'steps' ? 'selected' : ''}
                onClick={() => setTab('steps')}
              >
                Действия
              </button>
              <button
                aria-pressed={tab === 'files'}
                className={tab === 'files' ? 'selected' : ''}
                onClick={() => setTab('files')}
                disabled={!files.length}
              >
                Файлы ({files.length})
              </button>
            </div>
            {tab === 'steps' ? (
              <ol className="plan-steps">
                {plan.steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            ) : (
              <div className="plan-files">
                <div className="file-list">
                  {files.map((name) => (
                    <button
                      key={name}
                      onClick={() => setFile(name)}
                      className={(file || files[0]) === name ? 'selected' : ''}
                    >
                      {name}
                    </button>
                  ))}
                </div>
                <pre tabIndex={0}>{plan.files[file || files[0]]}</pre>
              </div>
            )}
            {['fresh', 'restore'].includes(action) && (
              <p className="feature-hint">
                Существующая панель не перезаписывается. Сервер будет проверен повторно перед
                установкой.
              </p>
            )}
            {action === 'tcp_tuning' && <p className="feature-hint">Изменяется системный алгоритм для новых TCP-сокетов и управляемые Nodekit sysctl/modules-load файлы. Действующие SSH-сессии не переключаются автоматически; для них требуется отдельное переподключение. Чужие файлы конфигурации сохраняются.</p>}
            {action === 'subscription_maintenance' && <p className="feature-hint">
              Аудит читает настройки, DNS и один публичный URL подписки без изменения сервисов.
              Ручной сброс серверного кэша реализован только через перезапуск принадлежащего Nodekit контейнера 3x-ui и может прервать VPN-соединения. Кэш V2BOX, Hiddify, DNS ОС и shared Caddy не затрагиваются.
            </p>}
            {action === 'configure' && <p className="feature-hint">
              Панель и Xray кратковременно перезапустятся; активные VPN-соединения могут прерваться. Будет заменён только сохранённый сайт этой ноды в Caddy.
              Существующие inbound и клиенты не редактируются. Разрешённые изменения UFW и публикаций Caddy перечислены в плане.
            </p>}
            {action === 'xhttp' && <p className="feature-hint">Изменяется только управляемый XHTTP inbound и принадлежащие Nodekit маршруты Caddy. Backend остаётся приватным, UFW ограничивается сетью Caddy. У других сайтов Caddy и контейнеров Docker ничего не меняется. Для корректной подписки отдельно проверь Hosts override.</p>}
            {action === 'tunnel' && plan.options?.tunnel?.members?.length && <p className="feature-hint">Пул поднимет несколько независимых systemd SSH-процессов и создаст roundRobin с observatory и fallback=blocked. Один общий выходной сервер не заменяет независимое резервирование. Xray будет перезапущен.</p>}
            {action === 'tunnel' && !plan.options?.tunnel?.members?.length && <p className="feature-hint">Будет включена systemd-служба SSH и добавлен маршрут для всех клиентов выбранного inbound. Xray перезапустится. UUID и ключи сохраняются; при ошибке выполняется откат. Ключ и known_hosts должны быть подготовлены на московской VPS.</p>}
            {action === 'client_import' && <p className="feature-hint">Из проверенного SQLite импортируются выбранные UUID и subId. Если включено восстановление связанных подписок, дополнительный шаг добавит недостающие HTTPS-ссылки на других клиентов из этой же базы через Clients API (без замены существующих чужих связей). Перед записью создаётся снимок целевой базы; Caddy и SSH не меняются.</p>}
            {action === 'traffic' && <p className="feature-hint">Будет запущен временный Xray-клиент на loopback VPS. Его конфигурация с секретами удалится после проверки. Маршруты сервера не меняются; пробный трафик учитывается у выбранного клиента.</p>}
            {action === 'inbound' && <p className="feature-hint">Перед изменением проверяется актуальность inbound и сохраняется SQLite snapshot на VPS. Удаление удаляет также его клиентов; при редактировании их идентификаторы и ключи сохраняются.</p>}
          </>
        )
      )}
    </Modal>
  );
}
