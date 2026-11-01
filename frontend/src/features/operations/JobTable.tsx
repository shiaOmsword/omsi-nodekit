import { ArrowUpRight } from 'lucide-react';
import type { Job, NodeSummary } from '../../types';
import { actionLabels, formatDate } from '../../app/format';
import { statusLabel } from '../../framework/messages';
import { EmptyState } from '../../framework/components';

export function JobStatus({ status }: { status: string }) {
  return (
    <span className={'job-status-badge ' + status}>
      <span />
      {statusLabel(status)}
    </span>
  );
}

export function JobTable({
  jobs,
  nodes,
  onOpen,
  empty = 'Операций пока нет',
}: {
  jobs: Job[];
  nodes: NodeSummary[];
  onOpen: (id: string) => void;
  empty?: string;
}) {
  if (!jobs.length)
    return (
      <EmptyState
        title={empty}
        description="Запусти операцию на странице ноды. Здесь появится её результат."
      />
    );
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Операция</th>
            <th>Нода</th>
            <th>Статус</th>
            <th>Начало</th>
            <th>
              <span className="sr-only">Результат</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>
                <button className="table-link" onClick={() => onOpen(job.id)}>
                  {actionLabels[job.action].title}
                </button>
                <small className="table-secondary mono">{job.id.slice(0, 8)}</small>
              </td>
              <td>{nodes.find((n) => n.id === job.node_id)?.name || job.node_id}</td>
              <td>
                <JobStatus status={job.status} />
              </td>
              <td className="nowrap">{formatDate(job.created_at)}</td>
              <td>
                <button
                  className="icon-button"
                  aria-label={'Результат операции ' + job.id.slice(0, 8)}
                  onClick={() => onOpen(job.id)}
                >
                  <ArrowUpRight size={19} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
