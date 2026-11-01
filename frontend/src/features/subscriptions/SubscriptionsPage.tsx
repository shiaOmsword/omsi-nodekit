import { useEffect, useMemo, useState } from 'react';
import { Activity, RefreshCw, ShieldAlert, Users } from 'lucide-react';
import { api } from '../../framework/api';
import { parse } from 'yaml';
import { Alert, Button, Loading, PageHeading, StatusBadge } from '../../framework/components';
import { formatDate } from '../../app/format';
import type {
  InboundFinding, InstallationReport, Job, JobDetail, JobOptions, NodeRecord, NodeSummary,
} from '../../types';

const CACHE_HINTS = [
  { name: 'Настройки inbound', ttl: '10 секунд', description: '3x-ui сбрасывает кэш при собственных изменениях. Ручная очистка обычно не нужна.' },
  { name: 'Вложенные подписки', ttl: '5 минут', description: '3x-ui может вернуть прежние конфигурации, если повторное скачивание не удалось.' },
  { name: 'DNS / V2BOX / Hiddify', ttl: 'На стороне клиента', description: 'Nodekit не может очищать кэш других приложений или публичных DNS-резолверов.' },
];

export function SubscriptionsPage({
  nodes, jobs, busy, onDiscover, onPreview, onClient, onRestoreClients, onOpenJob,
}: {
  nodes: NodeSummary[];
  jobs: Job[];
  busy: boolean;
  onDiscover: (record: NodeRecord) => void;
  onPreview: (record: NodeRecord, options: JobOptions) => void;
  onClient: (record: NodeRecord, inbound: InboundFinding, remove: boolean) => void;
  onRestoreClients: (record: NodeRecord, inbound: InboundFinding, report: InstallationReport) => void;
  onOpenJob: (id: string) => void;
}) {
  const activeNodes = nodes.filter((item) => item.state !== 'archived');
  const [selectedId, setSelectedId] = useState(activeNodes[0]?.id || '');
  const [record, setRecord] = useState<NodeRecord | null>(null);
  const [report, setReport] = useState<InstallationReport | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [inboundId, setInboundId] = useState<number | null>(null);
  const [clientEmail, setClientEmail] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);

  const latestReportIds = useMemo(
    () => jobs.filter((job) => job.node_id === selectedId && job.status === 'succeeded')
      .slice(0, 14).map((job) => job.id).join(','),
    [jobs, selectedId],
  );

  const lastMaintenanceId = jobs.find((job) =>
    job.node_id === selectedId && job.action === 'subscription_maintenance')?.id;
  const [lastMaintenance, setLastMaintenance] = useState<JobDetail | null>(null);
  const jobForStatus = jobs.find((job) => job.node_id === selectedId
    && ['queued', 'running'].includes(job.status));
  const needsRefresh = !!jobForStatus;

  useEffect(() => {
    let alive = true;
    setReading(true);
    setError('');
    setRecord(null);
    setReport(null);
    setInboundId(null);
    setClientEmail('');
    setAcknowledged(false);
    if (!selectedId) {
      setReading(false);
      return () => { alive = false; };
    }
    async function load() {
      const node = await api<NodeRecord>('/nodes/' + selectedId);
      const details = latestReportIds
        ? await Promise.all(latestReportIds.split(',').map((id) =>
            api<JobDetail>('/jobs/' + id).catch(() => null)))
        : [];
      const config = parse(node.yaml);
      const last = details.find((entry) =>
        entry?.report?.selected_panel
        && entry.report.ssh_host === config.ssh?.host
        && entry.report.ssh_port === (config.ssh?.port || 22)
      )?.report || null;
      if (!alive) return;
      setRecord(node);
      setReport(last);
    }
    void load()
      .catch(() => { if (alive) setError('Не удалось прочитать ноду или её отчёт.'); })
      .finally(() => { if (alive) setReading(false); });
    return () => { alive = false; };
  }, [selectedId, latestReportIds]);

  useEffect(() => {
    let alive = true;
    setLastMaintenance(null);
    if (lastMaintenanceId) {
      void api<JobDetail>('/jobs/' + lastMaintenanceId)
        .then((result) => { if (alive) setLastMaintenance(result); })
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [lastMaintenanceId, jobs.find((job) => job.id === lastMaintenanceId)?.status]);

  const panel = report?.panels.find((item) => item.id === report.selected_panel);
  const inbounds = panel?.installation === 'managed' && panel.inbounds_readable
    ? (panel.inbounds || []).filter((item) => item.protocol === 'vless')
    : [];
  const inbound = inbounds.find((item) => item.id === inboundId) || inbounds[0];
  const clients = inbound?.clients || [];
  const chosenEmail = clients.some((client) => client.email === clientEmail)
    ? clientEmail : clients.find((client) => client.enabled && client.has_subscription)?.email || '';
  const managed = record && panel?.installation === 'managed';
  const canAudit = !!managed && !!inbound?.fingerprint && !reading && !busy && !needsRefresh;
  const restartAllowed = canAudit && record?.yaml.includes('panel_runtime: docker') === true
    && !!panel?.container;
  const lastAudit = jobs.find((job) => job.node_id === selectedId && job.action === 'subscription_maintenance');

  function preview(mode: 'audit' | 'clear_server_cache') {
    if (!record || !inbound || !inbound.fingerprint) return;
    onPreview(record, {
      subscription_maintenance: {
        id: inbound.id,
        expected_fingerprint: inbound.fingerprint,
        mode,
        ...(chosenEmail ? { client_email: chosenEmail } : {}),
        ...(mode === 'clear_server_cache' ? { acknowledge_restart: true } : {}),
      },
    });
  }

  return <>
    <PageHeading title="Подписки и клиенты"
      description="Управление VLESS-ключами, проверка публичной выдачи и безопасное обслуживание кэшей 3x-ui."
      actions={<Button disabled={!record || busy} onClick={() => record && onDiscover(record)}
        icon={<RefreshCw size={17} />}>Обновить обнаружение</Button>} />
    <section className="card">
      <div className="form-grid">
        <label>Московская / зарубежная нода
          <select aria-label="Выбрать ноду для работы с подписками"
            value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            {!activeNodes.length && <option value="">Ноды отсутствуют</option>}
            {activeNodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
          </select>
        </label>
        <label>Входящий VLESS (inbound)
          <select aria-label="Выбрать VLESS inbound" value={inbound?.id || ''}
            disabled={!inbounds.length} onChange={(e) => {
              setInboundId(Number(e.target.value) || null);
              setClientEmail('');
              setAcknowledged(false);
            }}>
            {!inbounds.length && <option value="">Сначала выполни обнаружение</option>}
            {inbounds.map((item) => <option key={item.id} value={item.id}>
              {item.remark || 'Inbound ' + item.id} · #{item.id} · {item.client_count} клиентов
            </option>)}
          </select>
        </label>
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {reading && <Loading label="Загрузка ноды и последнего отчёта…" />}
      {!reading && !inbounds.length && <p className="feature-hint">
        Для управления нужен свежий отчёт обнаружения управляемой панели 3x-ui.
        Проверь, что в YAML выбрана правильная VPS, затем нажми «Обновить обнаружение».
      </p>}
      {report && <p className="feature-hint">
        Снимок конфигурации: {formatDate(report.observed_at)}. Перед выполнением сервер ещё раз
        проверит fingerprint inbound и принадлежность панели.
      </p>}
    </section>

    {inbound && <>
      <section className="card">
        <div className="section-heading">
          <div><h2>Клиенты и ключи</h2>
            <p className="muted">UUID и subId остаются на VPS; здесь показаны только имена и состояние.</p></div>
          <div className="row-actions">
            <Button disabled={!canAudit} onClick={() => record && onClient(record, inbound, false)}>
              + Клиент
            </Button>
            <Button disabled={!canAudit || !clients.length}
              onClick={() => record && onClient(record, inbound, true)}>− Клиент</Button>
            <Button disabled={!canAudit || !report}
              onClick={() => record && report && onRestoreClients(record, inbound, report)}>Из бэкапа</Button>
          </div>
        </div>
        <div className="table-scroll"><table className="data-table"><thead>
          <tr><th>Email / имя</th><th>Доступ</th><th>Подписка</th></tr>
        </thead><tbody>
          {clients.map((client) => <tr key={client.email}>
            <td>{client.email || 'Без имени'}</td>
            <td><StatusBadge tone={client.enabled ? 'mint' : 'amber'}>
              {client.enabled ? 'Включён' : 'Выключен'}</StatusBadge></td>
            <td>{client.has_subscription ? 'subId сохранён' : 'Нет subId'}</td>
          </tr>)}
          {!clients.length && <tr><td colSpan={3}>Пока нет клиентов</td></tr>}
        </tbody></table></div>
      </section>
      <section className="card">
        <div className="section-heading"><h2>Проверка подписки</h2>
          <Activity size={22}/></div>
        <p className="feature-hint">Nodekit проверяет DNS с VPS, адрес subURI, сертификат HTTPS,
          код ответа и число профилей. URL с subId, UUID и тело подписки в лог не записываются.
          Проверка не очищает серверный или мобильный кэш.</p>
        <div className="form-grid">
          <label>Клиент для проверки (необязательно)
            <select aria-label="Выбрать клиента для проверки подписки" value={chosenEmail}
              onChange={(e) => setClientEmail(e.target.value)}>
              <option value="">Только DNS и настройки панели</option>
              {clients.filter((client) => client.has_subscription).map((client) =>
                <option key={client.email} value={client.email}>{client.email}</option>)}
            </select>
          </label>
          <div className="row-actions" style={{alignItems: 'end'}}>
            <Button variant="primary" disabled={!canAudit} onClick={() => preview('audit')}>
              Проверить DNS и HTTPS
            </Button>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="section-heading"><h2>Серверный кэш 3x-ui</h2><ShieldAlert size={22}/></div>
        <div className="subscription-checks">
          {CACHE_HINTS.map((item) => <div className="subscription-check" key={item.name}>
            <div><strong>{item.name}</strong><span className="tag">{item.ttl}</span></div>
            <p>{item.description}</p>
          </div>)}
        </div>
        <Alert tone="warning">В 3x-ui 3.11.0 нет отдельного API для сброса кэша
          вложенных подписок. Принудительный сброс требует перезапуска **только**
          принадлежащего Nodekit Docker-контейнера панели. Это затронет все inbound
          этой панели и может кратко отключить VPN; Caddy и SSH не перезапускаются.</Alert>
        <label className="feature-hint">
          <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
          Я понимаю, что VPN-сессии на этой панели могут прерваться
        </label>
        <div className="row-actions">
          <Button disabled={!restartAllowed || !acknowledged} onClick={() => preview('clear_server_cache')}>
            Сбросить серверный кэш (перезапуск панели)
          </Button>
        </div>
        {!restartAllowed && <p className="feature-hint">
          Очистка доступна только управляемой Docker-панели с подтверждённым ownership.
          Для native/чужой панели здесь предусмотрен только аудит.
        </p>}
      </section>
      {lastAudit && <section className="card">
        <div className="section-heading"><h2>Последняя проверка или очистка</h2>
          <Button small onClick={() => onOpenJob(lastAudit.id)}>Открыть журнал</Button></div>
        <p className="feature-hint">Статус: {lastAudit.status} · {formatDate(lastAudit.created_at)}</p>
        {lastMaintenance?.events.slice(-8).map((event) => <p className="feature-hint" key={event.seq}>
          {event.message}
        </p>)}
      </section>}
    </>}
  </>;
}
