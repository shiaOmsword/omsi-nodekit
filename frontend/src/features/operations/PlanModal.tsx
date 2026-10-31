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
      title={actionLabels[action].title + ': план'}
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
            variant="primary"
            onClick={onLaunch}
            disabled={!plan}
            loading={busy}
            icon={<Play size={16} />}
          >
            Запустить операцию
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
                className={'tag ' + (['fresh', 'restore', 'configure'].includes(action) ? 'tag-warning' : '')}
              >
                {['fresh', 'restore', 'configure'].includes(action)
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
              Существующие inbound и клиенты не редактируются. Публикация портов и firewall общего Caddy не меняются.
            </p>}
          </>
        )
      )}
    </Modal>
  );
}
