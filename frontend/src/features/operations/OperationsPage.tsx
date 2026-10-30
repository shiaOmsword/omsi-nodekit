import { useState } from 'react';
import { ArrowLeft, ArrowUpRight, Download, FileText } from 'lucide-react';
import type { Job, JobDetail, NodeSummary } from '../../types';
import {
  Alert,
  Button,
  EmptyState,
  Loading,
  PageHeading,
  SearchInput,
} from '../../framework/components';
import { actionLabels, downloadLog, formatDate } from '../../app/format';
import { JobStatus, JobTable } from './JobTable';
import { InstallationReportView } from '../nodes/InstallationReportView';

export function OperationsPage({
  jobs,
  nodes,
  navigate,
}: {
  jobs: Job[];
  nodes: NodeSummary[];
  navigate: (path: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [node, setNode] = useState('all');
  const visible = jobs.filter(
    (j) =>
      (status === 'all' || j.status === status) &&
      (node === 'all' || j.node_id === node) &&
      (actionLabels[j.action].title + j.node_id + j.id)
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        title="Операции"
        description="История запусков, результаты и ошибки по всем нодам."
      />
      <div className="toolbar">
        <div className="toolbar-filters">
          <select
            aria-label="Фильтр по ноде"
            value={node}
            onChange={(e) => setNode(e.target.value)}
          >
            <option value="all">Все ноды</option>
            {[...new Set([...nodes.map((n) => n.id), ...jobs.map((j) => j.node_id)])].map((id) => (
              <option value={id} key={id}>
                {nodes.find((n) => n.id === id)?.name || id}
              </option>
            ))}
          </select>
          <select
            aria-label="Фильтр по статусу"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">Все статусы</option>
            <option value="running">Выполняется</option>
            <option value="queued">В очереди</option>
            <option value="succeeded">Завершено</option>
            <option value="failed">Ошибка</option>
            <option value="interrupted">Прервано</option>
          </select>
        </div>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Операция, нода или ID"
          label="Поиск операций"
        />
      </div>
      <section className="card">
        <JobTable
          jobs={visible}
          nodes={nodes}
          onOpen={(id) => navigate('/operations/' + id)}
          empty={jobs.length ? 'Нет операций по выбранным фильтрам' : undefined}
        />
      </section>
      <p className="page-note">
        Показана доступная история локальной панели. Статус операции не заменяет проверку
        VPN-трафика.
      </p>
    </>
  );
}

export function OperationDetail({
  job,
  error,
  nodes,
  navigate,
  onConfigure,
  onSuggest,
}: {
  job: JobDetail | null;
  error: string;
  nodes: NodeSummary[];
  navigate: (path: string) => void;
  onConfigure: (job: JobDetail) => void;
  onSuggest: (job: JobDetail) => void;
}) {
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!job) return <Loading />;
  const node = nodes.find((n) => n.id === job.node_id);
  return (
    <>
      <Button variant="text" onClick={() => navigate('/operations')} icon={<ArrowLeft size={17} />}>
        Все операции
      </Button>
      <PageHeading
        title={actionLabels[job.action].title}
        description={(node?.name || job.node_id) + ' · ' + formatDate(job.created_at)}
        actions={
          <>
            <Button onClick={() => navigate('/logs/' + job.id)} icon={<FileText size={17} />}>
              Открыть лог
            </Button>
            <Button onClick={() => downloadLog(job)} icon={<Download size={17} />}>
              Скачать .log
            </Button>
          </>
        }
      />
      <section className="card operation-summary">
        <div>
          <span>Статус</span>
          <JobStatus status={job.status} />
        </div>
        <div>
          <span>Завершена</span>
          <strong>{formatDate(job.finished_at)}</strong>
        </div>
        <div>
          <span>Нода</span>
          {node ? (
            <button className="table-link" onClick={() => navigate('/nodes/' + node.id)}>
              {node.name}
              <ArrowUpRight size={15} />
            </button>
          ) : (
            <strong>{job.node_id} · запись удалена</strong>
          )}
        </div>
      </section>
      {job.error && <Alert tone="error">{job.error}</Alert>}
      {job.backup_id && (
        <a className="button primary" href={'/api/backups/' + job.backup_id + '/download'}>
          <Download size={18} />
          Скачать созданный бэкап
        </a>
      )}
      {job.report ? (
        <InstallationReportView
          report={job.report}
          node={job.node_id}
          suggestions={
            node && (
              <div className="report-actions">
                <Button onClick={() => onSuggest(job)}>Заполнить настройки по отчёту</Button>
                {!job.report.panels.length && !job.report.warnings.length && (
                  <Button variant="primary" onClick={() => onConfigure(job)}>
                    Настроить установку
                  </Button>
                )}
              </div>
            )
          }
        />
      ) : (
        <section className="card">
          <EmptyState
            title={
              ['queued', 'running'].includes(job.status)
                ? 'Операция выполняется'
                : 'Отчёт не сформирован'
            }
            description="Подробности доступны в логе операции."
            action={<Button onClick={() => navigate('/logs/' + job.id)}>Открыть лог</Button>}
          />
        </section>
      )}
    </>
  );
}
