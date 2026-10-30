import { Activity, Archive, ArrowRight, CheckCircle2, Plus, Server } from 'lucide-react';
import type { Workspace } from '../../app/useWorkspace';
import { isRunning } from '../../app/format';
import { Button, EmptyState, PageHeading } from '../../framework/components';
import { JobStatus, JobTable } from '../operations/JobTable';

export function DashboardPage({
  workspace: w,
  navigate,
  onCreate,
}: {
  workspace: Workspace;
  navigate: (path: string) => void;
  onCreate: () => void;
}) {
  const stats = [
    {
      label: 'Ноды',
      value: w.nodes.length,
      icon: Server,
      hint: w.nodes.filter((n) => n.state === 'archived').length + ' в архиве',
    },
    {
      label: 'Выполняются',
      value: w.jobs.filter(isRunning).length,
      icon: Activity,
      hint: 'операций сейчас',
    },
    { label: 'Бэкапы', value: w.backups.length, icon: Archive, hint: 'сохранённых снимков' },
    {
      label: 'Завершены',
      value: w.jobs.filter((j) => j.status === 'succeeded').length,
      icon: CheckCircle2,
      hint: 'в доступной истории',
    },
  ];
  return (
    <>
      <PageHeading
        title="Обзор"
        description="Ноды, текущие операции и резервные копии."
        actions={
          <Button variant="primary" icon={<Plus size={18} />} onClick={onCreate}>
            Добавить ноду
          </Button>
        }
      />
      <div className="stat-grid">
        {stats.map((stat) => (
          <section className="stat-card" key={stat.label}>
            <div>
              <span>{stat.label}</span>
              <stat.icon size={19} />
            </div>
            <strong>{stat.value}</strong>
            <small>{stat.hint}</small>
          </section>
        ))}
      </div>
      {!w.nodes.length ? (
        <section className="card">
          <EmptyState
            title="Добавь первую ноду"
            description="Укажи адрес сервера и SSH-ключ. После подключения можно обнаружить установку или развернуть новую панель."
            action={
              <Button onClick={onCreate} variant="primary">
                Добавить ноду
              </Button>
            }
          />
        </section>
      ) : (
        <section className="card">
          <div className="section-heading">
            <div>
              <h2>Ноды</h2>
              <p>Последние операции по серверам</p>
            </div>
            <Button
              variant="text"
              onClick={() => navigate('/nodes')}
              icon={<ArrowRight size={17} />}
            >
              Все ноды
            </Button>
          </div>
          <div className="dashboard-node-grid">
            {w.nodes
              .filter((n) => n.state === 'active')
              .slice(0, 4)
              .map((node) => {
                const job = w.jobs.find((j) => j.node_id === node.id);
                return (
                  <button
                    className="dashboard-node"
                    key={node.id}
                    onClick={() => navigate('/nodes/' + node.id)}
                  >
                    <span className="node-symbol">
                      <Server size={20} />
                    </span>
                    <span>
                      <strong>{node.name}</strong>
                      <small>{node.id}</small>
                    </span>
                    {job ? (
                      <JobStatus status={job.status} />
                    ) : (
                      <span className="muted">Нет проверок</span>
                    )}
                    <ArrowRight size={17} />
                  </button>
                );
              })}
          </div>
          {!w.nodes.some((n) => n.state === 'active') && (
            <p className="card-content muted">
              В активном списке нет нод. Проверь скрытые записи и архив.
            </p>
          )}
        </section>
      )}
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Последние операции</h2>
            <p>Результаты и ход выполнения</p>
          </div>
          <Button variant="text" onClick={() => navigate('/operations')}>
            Весь журнал <ArrowRight size={17} />
          </Button>
        </div>
        <JobTable
          jobs={w.jobs.slice(0, 5)}
          nodes={w.nodes}
          onOpen={(id) => navigate('/operations/' + id)}
        />
      </section>
    </>
  );
}
