import { useEffect, useState } from 'react';
import { parse } from 'yaml';
import {
  Activity,
  Gauge,
  ArrowLeft,
  ArrowRight,
  Database,
  FileCode2,
  MoreHorizontal,
  Play,
  Save,
  Settings2,
  ShieldCheck,
  Stethoscope,
  Upload,
} from 'lucide-react';
import type { Workspace } from '../../app/useWorkspace';
import type { Action, Backup, JobDetail, InboundFinding } from '../../types';
import type { Route } from '../../framework/navigation/router';
import { Button, EmptyState, Loading, PageHeading } from '../../framework/components';
import { actionLabels, formatDate, isRunning } from '../../app/format';
import { messages } from '../../framework/messages';
import { InstallationReportView } from './InstallationReportView';
import { JobTable } from '../operations/JobTable';
import { InboundReport, SubscriptionReport } from './SubscriptionReport';
import { NetworkBenchmarkPanel } from './NetworkBenchmarkPanel';
import type { BenchmarkProfile } from '../../types';
import { NetworkReport } from './NetworkReport';

const actionIcons = {
  check: ShieldCheck,
  doctor: Stethoscope,
  fresh: Upload,
  restore: Database,
  backup: Save,
  configure: Settings2,
  attach_caddy: Settings2,
  inbound: Settings2,
  traffic: Activity,
  tcp_tuning: Gauge,
  system_backup: Save,
  system_restore: Database,
  network_benchmark: Gauge,
  tunnel: Activity,
  tunnel_restart: Activity,
  tunnel_route: Activity,
  xhttp: Activity,
  wireguard: Activity,
  client_import: Database,
  subscription_maintenance: Activity,
};
type NodeRoute = Extract<Route, { page: 'node' }>;

export function NodePage({
  route,
  workspace: w,
  reportJob,
  navigate,
  onEdit,
  onManage,
  onDeployment,
  onSuggest,
  onPlan,
  onImport,
  preferredBackup,
  onInbound,
  onXHTTP,
  onWireGuard,
  onPublishXHTTP,
  onPreparePool,
  onTunnelPool,
  onClient,
  onRestoreClients,
  onTraffic,
  onTunnel,
  onRestartTunnels,
  onTunnelRoutes,
  onTCPTuning,
  onBenchmark,
}: {
  route: NodeRoute;
  workspace: Workspace;
  reportJob: JobDetail | null;
  navigate: (path: string) => void;
  onEdit: () => void;
  onManage: () => void;
  onDeployment: () => void;
  onSuggest: (job: JobDetail) => void;
  onPlan: (action: Action, backupId?: string) => void;
  onImport: (done?: (backup: Backup) => void) => void;
  preferredBackup?: string;
  onInbound: (item: InboundFinding, remove: boolean) => void;
  onWireGuard: (item?: InboundFinding) => void;
  onXHTTP: (item?: InboundFinding) => void;
  onPublishXHTTP: (item: InboundFinding) => void;
  onPreparePool: () => void;
  onTunnelPool: () => void;
  onClient: (item: InboundFinding, remove: boolean) => void;
  onRestoreClients: (item: InboundFinding) => void;
  onTraffic: (item: InboundFinding) => void;
  onTunnel: () => void;
  onRestartTunnels: (names: string[]) => void;
  onTunnelRoutes: () => void;
  onBenchmark: (profile: BenchmarkProfile) => void;
  onTCPTuning: (algorithm: 'bbr' | 'cubic', fingerprint: string) => void;
}) {
  const [backupId, setBackupId] = useState(preferredBackup || '');
  const [tcpChoice, setTcpChoice] = useState<'bbr' | 'cubic'>('bbr');
  useEffect(() => {
    if (preferredBackup) setBackupId(preferredBackup);
  }, [preferredBackup]);
  if (w.nodeLoading) return <Loading label="Загрузка ноды…" />;
  if (!w.selected)
    return (
      <EmptyState
        title="Нода недоступна"
        description="Проверь выбранную запись или вернись к списку."
        action={<Button onClick={() => navigate('/nodes')}>Все ноды</Button>}
      />
    );
  const node = w.selected;
  const nodeJobs = w.jobs.filter((j) => j.node_id === node.id);
  const runningJob = nodeJobs.find(isRunning);
  const state = w.nodes.find((n) => n.id === node.id)?.state || node.state;
  const archived = state === 'archived';
  const locked = w.busy || !!runningJob || archived || w.dirty;
  const config = w.config;
  const sshTunnels: { name: string; host: string; ssh_port: number; local_port: number; target_port: number; host_key_policy?: 'strict' | 'accept-new' }[] = parse(node.yaml)?.tunnels || [];
  const sourceMatches =
    !!reportJob?.report &&
    reportJob.report.ssh_host === config?.ssh.host &&
    reportJob.report.ssh_port === (config?.ssh.port || 22);
  const report = sourceMatches ? reportJob?.report : null;
  const installation = config?.panel?.installation || 'managed';
  const action = route.action;
  const canDeploy = installation === 'managed';
  const attachmentNeeded = report?.caddy_attachment === 'required';
  const caddyReady = report?.caddy_attachment === 'ready';
  async function save() {
    await w.run(() => w.saveNode(w.yaml, node.id));
  }
  return (
    <>
      <Button variant="text" onClick={() => navigate('/nodes')} icon={<ArrowLeft size={17} />}>
        Все ноды
      </Button>
      <PageHeading
        title={node.name}
        description={
          (config?.ssh.user || 'root') +
          '@' +
          (config?.ssh.host || node.id) +
          ':' +
          (config?.ssh.port || 22)
        }
        actions={
          <>
            <span className={'node-state ' + state}>{messages.lifecycle.status[state]}</span>
            <Button onClick={onEdit} disabled={w.busy || w.dirty} icon={<Settings2 size={17} />}>
              Настройки
            </Button>
            <button className="icon-button" aria-label="Управление нодой" onClick={onManage}>
              <MoreHorizontal size={22} />
            </button>
          </>
        }
      />
      <nav className="page-tabs" aria-label="Разделы ноды">
        {[
          { id: 'overview', label: 'Обзор' },
          { id: 'inbounds', label: 'Inbound' },
          { id: 'tunnels', label: 'SSH-туннели' },
          { id: 'network', label: 'Сеть' },
          { id: 'operations', label: 'Операции' },
          { id: 'config', label: 'Конфигурация' },
          { id: 'history', label: 'История' },
        ].map((tab) => (
          <button
            key={tab.id}
            className={route.tab === tab.id ? 'selected' : ''}
            aria-current={route.tab === tab.id ? 'page' : undefined}
            onClick={() => navigate('/nodes/' + node.id + '/' + tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {archived && (
        <div className="info-banner">
          <span>Нода в архиве. Верни её в активные, чтобы запускать операции.</span>
          <Button small onClick={onManage}>
            Управление
          </Button>
        </div>
      )}
      {runningJob && (
        <div className="info-banner">
          <Activity size={18} />
          <span>
            {actionLabels[runningJob.action].title} ·{' '}
            {runningJob.status === 'queued' ? 'в очереди' : 'выполняется'}
          </span>
          <Button small onClick={() => navigate('/logs/' + runningJob.id)}>
            Открыть лог
          </Button>
        </div>
      )}
      {w.dirty && (
        <div className="info-banner">
          <span>Есть несохранённые изменения конфигурации.</span>
          <Button small onClick={save} loading={w.busy}>
            Сохранить
          </Button>
        </div>
      )}
      {route.tab === 'overview' && (
        <>
          <div className="node-overview-grid">
            <section className="card node-info">
              <h2>Подключение</h2>
              <dl className="detail-list">
                <dt>Сервер</dt>
                <dd>{config?.ssh.host}</dd>
                <dt>SSH-порт</dt>
                <dd>{config?.ssh.port || 22}</dd>
                <dt>Пользователь</dt>
                <dd>{config?.ssh.user || 'root'}</dd>
                <dt>SSH-ключ</dt>
                <dd>
                  {w.keys.find((k) => k.id === config?.ssh.key_id)?.name ||
                    config?.ssh.identity_file ||
                    'Не задан'}
                </dd>
              </dl>
              <Button variant="text" onClick={onEdit} disabled={w.dirty}>
                Изменить подключение <ArrowRight size={16} />
              </Button>
            </section>
            <section className="card next-step">
              <span className="node-symbol">
                <ShieldCheck size={24} />
              </span>
              <h2>
                {!report || report.warnings.length
                  ? 'Проверить сервер'
                  : report.panels.length
                    ? 'Проверить работу ноды'
                    : 'Подготовить 3x-ui'}
              </h2>
              <p>
                {!report || report.warnings.length
                  ? 'Обнаружение покажет установленные сервисы и параметры подключения.'
                  : report.panels.length
                    ? 'Диагностика проверит панель, сертификаты и настроенные туннели.'
                    : 'Панель не найдена. Выбери способ установки и нужные inbound.'}
              </p>
              <Button
                variant="primary"
                disabled={locked}
                onClick={() =>
                  !report || report.warnings.length
                    ? onPlan('check')
                    : report.panels.length
                      ? onPlan('doctor')
                      : onDeployment()
                }
              >
                {!report || report.warnings.length
                  ? 'Обнаружить конфигурацию'
                  : report.panels.length
                    ? 'Запустить диагностику'
                    : 'Настроить установку'}
                <ArrowRight size={17} />
              </Button>
            </section>
          </div>
          {report && reportJob ? (
            <InstallationReportView
              compact
              report={report}
              node={node.id}
              suggestions={
                <div className="report-actions">
                  <Button disabled={locked} onClick={() => onSuggest(reportJob)}>
                    Заполнить настройки по отчёту
                  </Button>
                  <Button variant="text" disabled={locked} onClick={() => onPlan('check')}>
                    Повторить обнаружение
                  </Button>
                  {canDeploy && config?.deployment?.caddy_mode === 'existing' && report.panels.length > 0 && (
                    <Button disabled={locked} onClick={() => navigate('/nodes/' + node.id + '/operations/configure')}>
                      Настроить подписки и inbound
                    </Button>
                  )}
                  <span className="muted">{formatDate(report.observed_at)}</span>
                </div>
              }
            />
          ) : (
            reportJob && (
              <p className="page-note">
                SSH-адрес изменился после последнего отчёта. Повтори обнаружение.
              </p>
            )
          )}
        </>
      )}
      {route.tab === 'operations' &&
        (!action ? (
          <div className="operation-grid">
            {(Object.keys(actionLabels) as Action[]).filter((id) => !['inbound', 'traffic', 'tunnel', 'tunnel_restart', 'tunnel_route', 'xhttp', 'client_import', 'tcp_tuning', 'network_benchmark', 'wireguard'].includes(id)).map((id) => {
              const Icon = actionIcons[id];
              return (
                <button
                  key={id}
                  className="card operation-card"
                  onClick={() => navigate('/nodes/' + node.id + '/operations/' + id)}
                >
                  <span className="node-symbol">
                    <Icon size={22} />
                  </span>
                  <h2>{actionLabels[id].title}</h2>
                  <p>{actionLabels[id].description}</p>
                  <span className="operation-card-link">
                    Открыть <ArrowRight size={17} />
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <section className="card operation-workspace">
            <div className="section-heading">
              <div>
                <h2>{actionLabels[action].title}</h2>
                <p>{actionLabels[action].description}</p>
              </div>
              <Button variant="text" onClick={() => navigate('/nodes/' + node.id + '/operations')}>
                Все операции
              </Button>
            </div>
            <div className="card-content">
              {['fresh', 'restore', 'configure', 'attach_caddy'].includes(action) && (
                <>
                  <div className="operation-setting">
                    <div>
                      <strong>{['configure', 'attach_caddy'].includes(action) ? 'Параметры подписок и inbound' : 'Параметры установки'}</strong>
                      <p>
                        {config?.deployment
                          ? (config.deployment.panel_runtime === 'native'
                              ? '3x-ui в системе'
                              : '3x-ui в Docker') +
                            ' · ' +
                            (config.deployment.caddy_mode === 'none'
                              ? 'без Caddy'
                              : config.deployment.caddy_mode === 'existing'
                                ? 'общий Caddy'
                                : 'новый Caddy')
                          : 'Выбери способ установки и HTTPS-сценарий.'}
                      </p>
                    </div>
                    <Button onClick={onDeployment} disabled={w.busy || w.dirty}>
                      Настроить
                    </Button>
                  </div>
                  {!canDeploy && (
                    <p className="report-warning">
                      Текущая конфигурация предназначена для существующей панели. Для новой
                      установки на пустую VPS сначала задай параметры развёртывания.
                    </p>
                  )}
                </>
              )}
              {['restore', 'system_restore'].includes(action) && (
                <div className="restore-picker">
                  <label htmlFor="restore-backup">Бэкап для восстановления</label>
                  <div>
                    <select
                      id="restore-backup"
                      value={backupId}
                      onChange={(e) => setBackupId(e.target.value)}
                    >
                      <option value="">Выбери снимок базы</option>
                      {w.backups.filter(b => action !== 'system_restore' || b.filename.endsWith('.nodekit.zip')).map((backup) => (
                        <option value={backup.id} key={backup.id}>
                          {backup.filename} · {formatDate(backup.created_at)}
                        </option>
                      ))}
                    </select>
                    <Button
                      onClick={() => onImport((b) => setBackupId(b.id))}
                      icon={<Upload size={17} />}
                    >
                      Загрузить .db
                    </Button>
                  </div>
                </div>
              )}
              <p className="feature-hint">
                {action === 'system_backup' ? 'Архив содержит приватные ключи. Он хранится вместе с бэкапами; raw Caddy и системные файлы сохраняются для справки.'
                  : action === 'system_restore' ? 'Вернуть системный TCP-алгоритм и отсутствующие ключи совпадающих SSH-туннелей. Сначала сохрани YAML новой VPS и выполни обнаружение. Установки и перезапуска сервисов здесь нет.'
                  : action === 'backup'
                  ? 'Согласованный снимок SQLite будет сохранён в разделе «Бэкапы».'
                  : action === 'attach_caddy'
                    ? 'Подключение Caddy к установленной панели. Существующие inbound и клиенты сохраняются. Панель перезапустится. Если выбран исходный контейнер Caddy этой ноды, он также кратковременно перезапустится для включения локального API.'
                  : action === 'configure'
                    ? 'Только установленная Nodekit панель с общим Caddy. Панель и Xray перезапустятся; активные VPN-соединения могут прерваться. Существующие inbound и клиенты сохраняются. Перед применением проверь параметры и план.'
                  : action === 'restore'
                    ? 'SQLite-бэкап сохраняет базу и клиентов, но не systemd-туннели, Caddy routes и Nodekit ownership. Восстановление доступно только на пустой цели.'
                    : action === 'fresh'
                      ? 'Новая установка требует пустой цели. Перед запуском будет повторная проверка сервисов и портов.'
                      : 'Операция читает конфигурацию сервера и не перенастраивает сервисы.'}
              </p>
              <div className="operation-footer">
                <span className="muted">Сначала проверишь план действий и файлы.</span>
                <Button
                  variant="primary"
                  icon={<Play size={17} />}
                  disabled={
                    locked ||
                    (['fresh', 'restore'].includes(action) && !canDeploy) ||
                    (['configure', 'attach_caddy'].includes(action) && (!canDeploy || config?.deployment?.caddy_mode !== 'existing')) ||
                    (['restore', 'system_restore'].includes(action) && !backupId) ||
                    (action === 'system_restore' && !report?.tcp_tuning)
                  }
                  onClick={() => onPlan(action, backupId)}
                >
                  Посмотреть план
                </Button>
              </div>
            </div>
          </section>
        ))}
      {route.tab === 'config' && (
        <>
          <div className="config-sections">
            <section className="card config-summary">
              <Settings2 size={22} />
              <div>
                <h2>Подключение к серверу</h2>
                <p>Адрес, SSH-ключ, пользователь и sudo.</p>
              </div>
              <Button disabled={w.busy || w.dirty} onClick={onEdit}>
                Изменить
              </Button>
            </section>
            <section className="card config-summary">
              <Upload size={22} />
              <div>
                <h2>Развёртывание</h2>
                <p>3x-ui, Caddy и межсерверные inbound.</p>
              </div>
              <Button disabled={w.busy || w.dirty} onClick={onDeployment}>
                Настроить
              </Button>
            </section>
          </div>
          <details className="card advanced-config">
            <summary>
              <FileCode2 size={19} />
              YAML-конфигурация<span className="muted">Все параметры, включая туннели</span>
            </summary>
            <div className="card-content">
              <label className="sr-only" htmlFor="node-yaml">
                YAML конфигурация ноды
              </label>
              <textarea
                id="node-yaml"
                className="yaml-editor"
                spellCheck={false}
                value={w.yaml}
                disabled={w.busy}
                onChange={(e) => w.setYaml(e.target.value)}
              />
              <div className="editor-footer">
                <span className="muted">
                  {w.dirty ? 'Изменения не сохранены' : 'Сохранённая конфигурация'}
                </span>
                <div className="row-actions">
                  <Button disabled={!w.dirty || w.busy} onClick={() => w.setYaml(node.yaml)}>
                    Отменить изменения
                  </Button>
                  <Button
                    variant="primary"
                    icon={<Save size={17} />}
                    disabled={!w.dirty}
                    loading={w.busy}
                    onClick={save}
                  >
                    Сохранить YAML
                  </Button>
                </div>
              </div>
            </div>
          </details>
        </>
      )}
      {route.tab === 'inbounds' && <section className="card"><div className="section-heading"><div><h2>Inbound ноды</h2><p>Изменение порта, SNI и названия; проверка трафика и управление UFW.</p></div>
        <div className="row-actions"><Button disabled={locked} onClick={() => onPlan('check')}>Обновить</Button><Button disabled={locked || !canDeploy || !report || !caddyReady || config?.deployment?.caddy_mode !== 'existing'} onClick={() => onXHTTP()}>+ VLESS / XHTTP</Button><Button disabled={locked || !canDeploy || !report} onClick={() => onWireGuard()}>+ WireGuard</Button><Button variant="primary" disabled={locked || !canDeploy} onClick={onDeployment}>+ VLESS / REALITY</Button></div></div>
        {config?.deployment?.caddy_mode !== 'existing' ? <div className="info-banner">
          <span>Для XHTTP выбери существующий Caddy в параметрах развёртывания.</span>
          <Button disabled={locked} onClick={onDeployment}>Настроить Caddy</Button>
        </div> : attachmentNeeded ? <div className="info-banner">
          <span>Caddy выбран в настройках, но ещё не подключён к установленной панели. Сначала подключи его, затем создай XHTTP.</span>
          <Button disabled={locked || !canDeploy} onClick={() => onPlan('attach_caddy')}>Подключить Caddy</Button>
        </div> : !caddyReady ? <p className="page-note">Обнови обнаружение, чтобы проверить подключение Caddy перед созданием XHTTP.</p> : null}
        <div className="card-content">{report?.selected_panel ? report.panels.filter((p) => p.id === report.selected_panel).map((panel) => <InboundReport key={panel.id} panel={panel} busy={locked}
          onEdit={panel.installation === 'managed' ? (item) => item.protocol === 'wireguard' ? onWireGuard(item) : item.network === 'xhttp' ? onXHTTP(item) : onInbound(item, false) : undefined}
          onDelete={(item) => onInbound(item, true)} onTest={onTraffic} onClient={onClient} onPublish={onPublishXHTTP} onRestoreClients={onRestoreClients} />) :
          <EmptyState title="Нужен актуальный отчёт выбранной панели" description="Запусти обнаружение и выбери установку 3x-ui." />}</div></section>}
      {route.tab === 'tunnels' && <section className="card">
        <div className="section-heading">
          <div><h2>SSH-туннели</h2><p>Отдельные процессы systemd, локальные TCP-порты и маршруты Xray. Состояние службы не равно проверке выхода.</p></div>
          <div className="row-actions">
            {sshTunnels.length === 1 && <Button disabled={locked} onClick={onPreparePool}>Подготовить 3 в YAML</Button>}
            <Button disabled={locked} onClick={() => onPlan('check')}>Обновить</Button>
            <Button disabled={locked || !canDeploy || !sshTunnels.length} onClick={() => onRestartTunnels(sshTunnels.map(t => t.name))}>Перезапустить все</Button>
            <Button disabled={locked || !canDeploy || !report?.ssh_exits?.length} onClick={onTunnelRoutes}>Настроить inbound</Button>
            <Button disabled={locked || !report} onClick={onTunnel}>Один туннель</Button>
            <Button variant="primary" disabled={locked || !report || sshTunnels.length < 2} onClick={onTunnelPool}>Поднять пул</Button>
          </div>
        </div>
        <div className="card-content">
          {!sshTunnels.length ? <EmptyState title="Нет туннелей в YAML" description="Добавь tunnels в конфигурации ноды: host, ssh_port, local_port, target_port, identity_file, known_hosts_file." /> :
            <div className="table-scroll"><table className="data-table"><thead><tr><th>Туннель</th><th>SSH</th><th>Локальный порт → выход</th><th>Ключ сервера</th><th>Systemd</th><th>Действия</th></tr></thead><tbody>
              {sshTunnels.map((t) => { const live = report?.tunnels?.find((item) => item.name === t.name);
                return <tr key={t.name}><td><strong>{t.name}</strong></td><td><code>{t.host}:{t.ssh_port || 22}</code></td>
                  <td><code>127.0.0.1:{t.local_port} → 127.0.0.1:{t.target_port}</code></td>
                  <td>{t.host_key_policy === 'accept-new' ? 'Автодоверие при первом подключении' : 'Только известный ключ'}</td>
                  <td>{live ? live.active ? 'Работает' : 'Не запущен' : 'Нет свежей проверки'}</td>
                  <td><Button small disabled={locked || !canDeploy} onClick={() => onRestartTunnels([t.name])}>Перезапустить</Button></td></tr>; })}
            </tbody></table></div>}
          {!!report?.ssh_exits?.length && <div className="report-section"><h3>Inbound SSH-выходов</h3>{report.ssh_exits.map(exit => <p key={exit.kind + ':' + exit.name}><strong>{exit.kind === 'pool' ? 'Пул ' : 'Туннель '}{exit.name}</strong>: {exit.inbound_ids.map(id => {
            const inbound = report.panels.find(p => p.id === report.selected_panel)?.inbounds?.find(i => i.id === id);
            return inbound ? `${inbound.remark || '#' + id} (${inbound.protocol.toUpperCase()})` : '#' + id;
          }).join(', ')}</p>)}</div>}
          <p className="feature-hint">Перезапуск кратковременно прервёт трафик через выбранные SSH-туннели. Сначала откроется план; после запуска проверятся службы и локальные порты. Новые SSH-соединения используют текущие настройки TCP.</p>
          <p className="feature-hint">Пул распределяет новые соединения по отдельным SSH-сессиям. При потере всех выходов fallback блокирует соединения, не подменяя зарубежный IP на российский. Существующие TCP-сессии не мигрируют автоматически.</p>
          <p className="feature-hint">Для независимого резервирования провайдеров/локаций одного пула недостаточно; здесь проверяется один общий выходной VLESS endpoint.</p>
          <p className="feature-hint">Неизвестный SSH fingerprint может автоматически приниматься только при явном host_key_policy: accept-new в YAML. Изменённый ключ известной ноды всегда отклоняется.</p>
        </div>
      </section>}
      {route.tab === 'network' && <NetworkBenchmarkPanel key={node.id} nodeId={node.id} jobs={nodeJobs} locked={locked} onPreview={onBenchmark} />}
      {route.tab === 'network' && <section className="card">
        <div className="section-heading">
          <div><h2>TCP congestion control</h2><p>Алгоритм новых TCP-соединений VPS. Не меняет текущие SSH-сессии.</p></div>
        </div>
        <div className="card-content">
          {!report?.tcp_tuning ? <p className="feature-hint">Запусти обнаружение, чтобы прочитать настройки ядра.</p> : <>
            <dl className="detail-list">
              <dt>Сейчас</dt><dd><strong>{report.tcp_tuning.current.toUpperCase()}</strong></dd>
              <dt>Доступно</dt><dd>{report.tcp_tuning.available.join(', ')}</dd>
              <dt>Настройка Nodekit</dt><dd>{report.tcp_tuning.managed_algorithm?.toUpperCase() || 'Не обнаружена (возможно, настроено вручную)'}</dd>
            </dl>
            {report.tcp_tuning.conflict && <p className="report-warning">Файл настроек Nodekit отличается от ожидаемого или является symlink. Изменения заблокированы.</p>}
            <div className="row-actions">
              <label htmlFor="tcp-algorithm">Алгоритм</label>
              <select id="tcp-algorithm" value={tcpChoice} onChange={(event) => setTcpChoice(event.target.value as 'bbr' | 'cubic')}>
                <option value="bbr">BBR</option>
                <option value="cubic">CUBIC</option>
              </select>
              <Button disabled={locked || report.tcp_tuning.conflict} onClick={() => onTCPTuning(tcpChoice, report.tcp_tuning!.fingerprint)}>
                Посмотреть план TCP
              </Button>
            </div>
            <p className="feature-hint">Настройка сохраняется при перезагрузке и действует по умолчанию для новых TCP-соединений всей VPS. SSH, 3x-ui и Caddy автоматически не перезапускаются.</p>
          </>}
        </div>
      </section>}
      {route.tab === 'network' && <section className="card"><div className="section-heading"><div><h2>Сеть и диагностика</h2><p>UFW, публикации Caddy, подписки и маршруты Xray.</p></div>
        <Button disabled={locked} onClick={() => onPlan('doctor')}>Запустить диагностику</Button></div><div className="card-content">
          {report ? <><NetworkReport report={report} /><SubscriptionReport report={report} /></> : <EmptyState title="Нет отчёта" description="Начни с обнаружения сервера." />}</div></section>}
      {route.tab === 'history' && (
        <section className="card">
          <div className="section-heading">
            <div>
              <h2>История ноды</h2>
              <p>{nodeJobs.length} операций в доступном журнале</p>
            </div>
          </div>
          <JobTable
            jobs={nodeJobs}
            nodes={w.nodes}
            onOpen={(id) => navigate('/operations/' + id)}
          />
        </section>
      )}
    </>
  );
}
