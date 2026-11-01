import { useEffect, useMemo, useState } from 'react';
import { api } from '../../framework/api';
import { parse } from 'yaml';
import { Alert, Button, Loading, Modal } from '../../framework/components';
import type {
  Backup, BackupClientCatalog, InboundFinding, InstallationReport, Job,
  JobDetail, JobOptions, NodeRecord, NodeSummary,
} from '../../types';

export function BackupClientsModal({
  backup, record, inbound, report, backups, nodes, jobs, busy, error, onClose, onPreview,
}: {
  backup?: Backup;
  record?: NodeRecord;
  inbound?: InboundFinding;
  report?: InstallationReport;
  backups: Backup[];
  nodes: NodeSummary[];
  jobs: Job[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onPreview: (node: NodeRecord, backup: Backup, options: JobOptions) => void;
}) {
  const [backupId, setBackupId] = useState(backup?.id || backups[0]?.id || '');
  const [nodeId, setNodeId] = useState(record?.id || '');
  const [node, setNode] = useState<NodeRecord | null>(record || null);
  const [inventory, setInventory] = useState<InstallationReport | null>(report || null);
  const [catalog, setCatalog] = useState<BackupClientCatalog | null>(null);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [destinationId, setDestinationId] = useState<number | null>(inbound?.id || null);
  const [selected, setSelected] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [nodeLoading, setNodeLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  // Polling updates jobs every four seconds; the dialog must not reset the
  // selected inbound unless a relevant job ID/status actually changes.
  const jobKey = jobs.filter((job) =>
    job.node_id === nodeId && job.status === 'succeeded').slice(0, 12)
    .map((job) => job.id).join(',');

  useEffect(() => {
    let alive = true;
    setCatalog(null);
    setSourceId(null);
    setSelected([]);
    setLoadError('');
    if (!backupId) return () => { alive = false; };
    setLoading(true);
    api<BackupClientCatalog>('/backups/' + encodeURIComponent(backupId) + '/clients')
      .then((result) => {
        if (!alive) return;
        setCatalog(result);
        setSourceId(result.inbounds.find((s) => s.clients.length > 0)?.id || null);
      })
      .catch(() => { if (alive) setLoadError('Не удалось прочитать клиентов из резервной базы.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [backupId]);

  useEffect(() => {
    let alive = true;
    setLoadError('');
    if (!nodeId) {
      setNode(null);
      setInventory(null);
      setDestinationId(null);
      return () => { alive = false; };
    }
    if (record?.id === nodeId && report) {
      setNode(record);
      setInventory(report);
      setDestinationId(inbound?.id || null);
      return () => { alive = false; };
    }
    setNodeLoading(true);
    setInventory(null);
    setDestinationId(null);
    async function load() {
      const selectedNode = await api<NodeRecord>('/nodes/' + nodeId);
      const cfg = parse(selectedNode.yaml);
      let last: InstallationReport | null = null;
      for (const jobId of (jobKey ? jobKey.split(',') : [])) {
        const detail = await api<JobDetail>('/jobs/' + jobId);
        if (
          detail.report?.selected_panel
          && detail.report.ssh_host === cfg.ssh?.host
          && detail.report.ssh_port === (cfg.ssh?.port || 22)
        ) {
          last = detail.report;
          break;
        }
      }
      if (alive) { setNode(selectedNode); setInventory(last); }
    }
    void load()
      .catch(() => { if (alive) setLoadError('Не удалось прочитать ноду или её отчёт.'); })
      .finally(() => { if (alive) setNodeLoading(false); });
    return () => { alive = false; };
  }, [nodeId, record, inbound, report, jobKey]);

  const source = catalog?.inbounds.find((s) => s.id === sourceId);
  const panel = inventory?.panels.find((p) => p.id === inventory.selected_panel);
  const destinations = panel?.installation === 'managed' && panel.inbounds_readable
    ? (panel.inbounds || []).filter((item) => item.protocol === 'vless' && !!item.fingerprint) : [];
  const destination = destinations.find((item) => item.id === destinationId);
  const currentBackup = backups.find((item) => item.id === backupId);
  const ready = source?.clients.filter((client) => client.restorable) || [];
  const visible = useMemo(() => source?.clients.filter((client) =>
    client.email.toLowerCase().includes(search.toLowerCase())) || [], [source, search]);

  function preview() {
    if (!node || !currentBackup || !source || !destination || !selected.length) return;
    onPreview(node, currentBackup, {
      client_import: {
        source_inbound_id: source.id,
        target_inbound_id: destination.id,
        expected_fingerprint: destination.fingerprint!,
        client_refs: selected,
      },
    });
  }

  return <Modal
    title="Перенос клиентов из SQLite-бэкапа"
    description="Копируются идентификаторы и политика доступа, не весь inbound."
    wide busy={busy} onClose={onClose}
    footer={<>
      <Button disabled={busy} onClick={onClose}>Отмена</Button>
      <Button variant="primary" loading={busy} onClick={preview}
        disabled={loading || nodeLoading || !source || !destination || !currentBackup || !selected.length || selected.length > 100}>
        Посмотреть план · {selected.length}
      </Button>
    </>}>
    {(error || loadError) && <Alert tone="error">{error || loadError}</Alert>}
    {!backups.length && <p className="feature-hint">Нет сохранённых дампов. Сначала загрузи x-ui.db на странице «Бэкапы».</p>}
    <div className="form-grid">
      <label>Исходный дамп
        <select value={backupId} disabled={busy} onChange={(event) => setBackupId(event.target.value)}>
          {backups.map((item) => <option key={item.id} value={item.id}>{item.filename} · {item.created_at}</option>)}
        </select>
      </label>
      <label>Целевая нода
        <select value={nodeId} disabled={busy || !!record} onChange={(event) => setNodeId(event.target.value)}>
          <option value="">Выбери VPS</option>
          {nodes.filter((item) => item.state !== 'archived').map((item) =>
            <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
    </div>
    {(loading || nodeLoading) && <Loading label="Чтение бэкапа и текущей конфигурации…" />}
    {catalog && <>
      <div className="form-grid">
        <label>Исходный inbound
          <select value={sourceId || ''} onChange={(event) => {
            setSourceId(Number(event.target.value) || null);
            setSelected([]);
          }}>
            <option value="">Выбери исходный inbound</option>
            {catalog.inbounds.map((item) => <option key={item.id} value={item.id}>
              {item.remark || '#' + item.id} · {item.client_count} клиентов
            </option>)}
          </select>
        </label>
        <label>Целевой VLESS inbound
          <select value={destinationId || ''} disabled={!destinations.length || !!inbound}
            onChange={(event) => setDestinationId(Number(event.target.value) || null)}>
            <option value="">Выбери inbound</option>
            {destinations.map((item) => <option key={item.id} value={item.id}>
              {item.remark || '#' + item.id} · {item.network} · {item.client_count} клиентов
            </option>)}
          </select>
        </label>
      </div>
      {nodeId && !nodeLoading && !destinations.length &&
        <p className="feature-hint">Нет свежего отчёта управляемой панели с VLESS inbound. Открой ноду и выполни «Обнаружение», затем вернись к импорту.</p>}
      {source && <>
        <div className="row-actions">
          <strong>Клиенты ({source.client_count})</strong>
          <Button small disabled={!ready.length} onClick={() => setSelected(ready.slice(0, 100).map((c) => c.ref))}>
            Выбрать доступных (макс. 100)
          </Button>
          <Button small disabled={!selected.length} onClick={() => setSelected([])}>
            Снять выбор
          </Button>
        </div>
        <input aria-label="Найти клиента в бэкапе" placeholder="Фильтр по email"
          value={search} onChange={(event) => setSearch(event.target.value)} />
        <div className="table-scroll" style={{ maxHeight: 260, overflowY: 'auto' }}>
          <table className="data-table"><thead><tr>
            <th>Перенести</th><th>Email</th><th>Состояние</th><th>Подписка</th>
          </tr></thead><tbody>
            {visible.map((client) => <tr key={client.ref}>
              <td><input type="checkbox" aria-label={'Выбрать ' + client.email}
                checked={selected.includes(client.ref)} disabled={!client.restorable || busy}
                onChange={(event) => setSelected((items) => event.target.checked
                  ? items.length < 100 ? [...items, client.ref] : items
                  : items.filter((value) => value !== client.ref))} /></td>
              <td>{client.email || 'Без имени'}</td>
              <td>{client.enabled ? 'Включён' : 'Выключен'}</td>
              <td>{client.restorable ? 'UUID и subId сохранены' : 'Нет корректного UUID / subId'}</td>
            </tr>)}
          </tbody></table>
        </div>
      </>}
    </>}
    <p className="feature-hint">
      ID подписок и UUID не показываются в интерфейсе, но передаются внутри защищённой операции
      без изменений. При дублировании email, UUID или subId с другой учётной записью импорт
      остановится. Существующих клиентов и настройки Caddy/SSH эта операция не изменяет.
    </p>
    <p className="feature-hint">
      При переносе с REALITY на XHTTP режим Vision flow очищается; привязки к старым Hosts
      и счётчики трафика не копируются. Для выдачи публичных ссылок используй Hosts целевого inbound.
    </p>
  </Modal>;
}
