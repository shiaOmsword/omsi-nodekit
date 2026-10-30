import { useEffect, useRef, useState } from 'react';
import { Download, ExternalLink } from 'lucide-react';
import type { Job, JobDetail, NodeSummary } from '../../types';
import {
  Alert,
  Button,
  EmptyState,
  Loading,
  PageHeading,
  SearchInput,
} from '../../framework/components';
import { actionLabels, downloadLog, formatDate, isRunning } from '../../app/format';
import { JobStatus } from '../operations/JobTable';

export function LogsPage({
  jobs,
  nodes,
  job,
  error,
  navigate,
}: {
  jobs: Job[];
  nodes: NodeSummary[];
  job: JobDetail | null;
  error: string;
  navigate: (path: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [level, setLevel] = useState('all');
  const [follow, setFollow] = useState(true);
  const consoleRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow) consoleRef.current?.scrollTo({ top: consoleRef.current.scrollHeight });
  }, [follow, job?.events.length]);
  const visible =
    job?.events.filter(
      (e) =>
        (level === 'all' || e.level === level) &&
        (e.message + e.created_at).toLowerCase().includes(search.toLowerCase()),
    ) || [];
  return (
    <>
      <PageHeading
        title="Логи"
        description="События выбранной операции в реальном времени."
        actions={
          job && (
            <>
              <Button
                onClick={() => navigate('/operations/' + job.id)}
                icon={<ExternalLink size={17} />}
              >
                Результат
              </Button>
              <Button onClick={() => downloadLog(job)} icon={<Download size={17} />}>
                Скачать полный лог
              </Button>
            </>
          )
        }
      />
      {!jobs.length ? (
        <section className="card">
          <EmptyState
            title="Логов пока нет"
            description="После запуска операции здесь появятся её события."
          />
        </section>
      ) : (
        <>
          <div className="log-select">
            <label htmlFor="log-job">Операция</label>
            <select
              id="log-job"
              value={job?.id || ''}
              onChange={(e) => navigate('/logs/' + e.target.value)}
            >
              {!job && <option value="">Загрузка операции…</option>}
              {jobs.map((j) => (
                <option value={j.id} key={j.id}>
                  {nodes.find((n) => n.id === j.node_id)?.name || j.node_id} ·{' '}
                  {actionLabels[j.action].title} · {formatDate(j.created_at)}
                </option>
              ))}
            </select>
          </div>
          <div className="toolbar">
            <div className="toolbar-filters">
              <select
                aria-label="Уровень событий"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              >
                <option value="all">Все события</option>
                <option value="info">Информация</option>
                <option value="warning">Предупреждения</option>
                <option value="error">Ошибки</option>
              </select>
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={follow}
                  onChange={(e) => setFollow(e.target.checked)}
                />
                Автопрокрутка
              </label>
            </div>
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Найти в сообщениях"
              label="Поиск в логе"
            />
          </div>
          {error ? (
            <Alert tone="error">{error}</Alert>
          ) : !job ? (
            <Loading />
          ) : (
            <section className="log-panel">
              <header>
                <div>
                  <span className={'status-dot' + (isRunning(job) ? ' live' : '')} />
                  <strong>{actionLabels[job.action].title}</strong>
                  <JobStatus status={job.status} />
                </div>
                <span className="mono">
                  {job.node_id} / {job.id.slice(0, 8)}
                </span>
              </header>
              <div
                className="log-events"
                ref={consoleRef}
                role="log"
                aria-label="События операции"
                aria-live={isRunning(job) ? 'polite' : 'off'}
                aria-relevant="additions text"
              >
                {visible.map((event) => (
                  <div className={'log-line ' + event.level} key={event.seq}>
                    <time>{formatDate(event.created_at)}</time>
                    <span className="log-level">
                      {event.level === 'error'
                        ? 'ERROR'
                        : event.level === 'warning'
                          ? 'WARN'
                          : 'INFO'}
                    </span>
                    <pre>{event.message}</pre>
                  </div>
                ))}
                {!visible.length && (
                  <p className="log-placeholder">
                    {job.events.length
                      ? 'Нет событий по выбранному фильтру.'
                      : isRunning(job)
                        ? 'Ожидание первых событий…'
                        : 'События не записаны.'}
                  </p>
                )}
              </div>
              <footer>
                {visible.length} из {job.events.length} событий
                {isRunning(job) && <span>Обновляется каждые 2 секунды</span>}
              </footer>
            </section>
          )}
        </>
      )}
    </>
  );
}
