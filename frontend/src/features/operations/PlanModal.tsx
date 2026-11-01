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
            {plan?.options?.inbound?.operation === 'delete' ? 'Удалить inbound' : 'Запустить операцию'}
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
                className={'tag ' + (['fresh', 'restore', 'configure', 'inbound', 'tunnel', 'xhttp'].includes(action) ? 'tag-warning' : '')}
              >
                {['fresh', 'restore', 'configure', 'inbound', 'tunnel', 'xhttp'].includes(action)
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
            {action === 'configure' && <p className="feature-hint">
              Панель и Xray кратковременно перезапустятся; активные VPN-соединения могут прерваться. Будет заменён только сохранённый сайт этой ноды в Caddy.
              Существующие inbound и клиенты не редактируются. Разрешённые изменения UFW и публикаций Caddy перечислены в плане.
            </p>}
            {action === 'xhttp' && <p className="feature-hint">Изменяется только управляемый XHTTP inbound и принадлежащие Nodekit маршруты Caddy. Backend остаётся приватным, UFW ограничивается сетью Caddy. У других сайтов Caddy и контейнеров Docker ничего не меняется. Для корректной подписки отдельно проверь Hosts override.</p>}
            {action === 'tunnel' && <p className="feature-hint">Будет включена systemd-служба SSH и добавлен маршрут для всех клиентов выбранного inbound. Xray перезапустится. UUID и ключи сохраняются; при ошибке выполняется откат. Ключ и known_hosts должны быть подготовлены на московской VPS.</p>}
            {action === 'traffic' && <p className="feature-hint">Будет запущен временный Xray-клиент на loopback VPS. Его конфигурация с секретами удалится после проверки. Маршруты сервера не меняются; пробный трафик учитывается у выбранного клиента.</p>}
            {action === 'inbound' && <p className="feature-hint">Перед изменением проверяется актуальность inbound и сохраняется SQLite snapshot на VPS. Удаление удаляет также его клиентов; при редактировании их идентификаторы и ключи сохраняются.</p>}
          </>
        )
      )}
    </Modal>
  );
}
