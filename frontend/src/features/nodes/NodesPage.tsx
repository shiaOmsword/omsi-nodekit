import { useState } from 'react';
import { ArrowRight, MoreHorizontal, Plus, Server } from 'lucide-react';
import type { NodeState, NodeSummary, Job } from '../../types';
import { Button, EmptyState, PageHeading, SearchInput } from '../../framework/components';
import { messages } from '../../framework/messages';
import { JobStatus } from '../operations/JobTable';
import { formatDate } from '../../app/format';

export function NodesPage({
  nodes,
  jobs,
  onOpen,
  onCreate,
  onManage,
}: {
  nodes: NodeSummary[];
  jobs: Job[];
  onOpen: (id: string) => void;
  onCreate: () => void;
  onManage: (node: NodeSummary) => void;
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<NodeState | 'all'>('active');
  const visible = nodes.filter(
    (node) =>
      (filter === 'all' || node.state === filter) &&
      (node.name + ' ' + node.id).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        title="Ноды"
        description="Подключения к серверам и управление их конфигурацией."
        actions={
          <Button variant="primary" onClick={onCreate} icon={<Plus size={18} />}>
            Добавить ноду
          </Button>
        }
      />
      <div className="toolbar">
        <div className="filter-tabs" role="group" aria-label="Состояние нод">
          {(['active', 'hidden', 'archived', 'all'] as const).map((state) => (
            <button
              key={state}
              className={filter === state ? 'selected' : ''}
              aria-pressed={filter === state}
              onClick={() => setFilter(state)}
            >
              {messages.lifecycle.filters[state]}
              <span>
                {state === 'all' ? nodes.length : nodes.filter((n) => n.state === state).length}
              </span>
            </button>
          ))}
        </div>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Название или ID ноды"
          label="Поиск нод"
        />
      </div>
      {!visible.length ? (
        <section className="card">
          <EmptyState
            title={nodes.length ? 'Ноды не найдены' : 'Пока нет нод'}
            description={
              nodes.length
                ? 'Измени фильтр или поисковый запрос.'
                : 'Добавь сервер, чтобы обнаружить его конфигурацию и запускать операции.'
            }
            action={
              !nodes.length && (
                <Button onClick={onCreate} variant="primary">
                  Добавить ноду
                </Button>
              )
            }
          />
        </section>
      ) : (
        <div className="node-grid">
          {visible.map((node) => {
            const job = jobs.find((j) => j.node_id === node.id);
            return (
              <article className="card node-card" key={node.id}>
                <div className="node-card-top">
                  <span className="node-symbol">
                    <Server size={22} />
                  </span>
                  <span className={'node-state ' + node.state}>
                    {messages.lifecycle.status[node.state]}
                  </span>
                  <button
                    className="icon-button"
                    aria-label={'Управление нодой ' + node.name}
                    onClick={() => onManage(node)}
                  >
                    <MoreHorizontal size={21} />
                  </button>
                </div>
                <button className="node-card-name" onClick={() => onOpen(node.id)}>
                  <h2>{node.name}</h2>
                  <span className="mono muted">{node.id}</span>
                </button>
                <div className="node-last-job">
                  <span>Последняя операция</span>
                  {job ? (
                    <>
                      <JobStatus status={job.status} />
                      <small>{formatDate(job.created_at)}</small>
                    </>
                  ) : (
                    <p className="muted">Ещё не запускалась</p>
                  )}
                </div>
                <Button full onClick={() => onOpen(node.id)}>
                  Открыть ноду <ArrowRight size={17} />
                </Button>
              </article>
            );
          })}
        </div>
      )}
    </>
  );
}
