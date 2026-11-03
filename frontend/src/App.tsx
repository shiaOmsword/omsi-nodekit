import { useEffect, useState } from 'react';
import { ArrowLeft, Upload } from 'lucide-react';
import { api } from './framework/api';
import {
  Alert,
  Button,
  CodeBlock,
  EmptyState,
  FormDialog,
  Loading,
  Modal,
} from './framework/components';
import type { FormField, FormValues } from './framework/components';
import { useWorkspaceRoute } from './framework/navigation/router';
import { preserveDeploymentIntent, readConfig } from './app/config';
import { isRunning } from './app/format';
import { Shell } from './app/Shell';
import { useJobDetail, useNodeReport, useWorkspace } from './app/useWorkspace';
import { DashboardPage } from './features/dashboard/DashboardPage';
import { NodesPage } from './features/nodes/NodesPage';
import { NodePage } from './features/nodes/NodePage';
import { NodeFormModal } from './features/nodes/NodeFormModal';
import { DeploymentModal } from './features/nodes/DeploymentModal';
import { InboundModal, ClientModal } from './features/nodes/InboundModal';
import { XHTTPModal } from './features/nodes/XHTTPModal';
import { TunnelPoolModal } from './features/nodes/TunnelPoolModal';
import { parse, stringify } from 'yaml';
import { TunnelModal } from './features/nodes/TunnelModal';
import { DiscoveryModal } from './features/nodes/DiscoveryModal';
import { NodeManagementModal } from './features/nodes/NodeManagementModal';
import { OperationsPage, OperationDetail } from './features/operations/OperationsPage';
import { PlanModal } from './features/operations/PlanModal';
import { BackupsPage } from './features/backups/BackupsPage';
import { SubscriptionsPage } from './features/subscriptions/SubscriptionsPage';
import { BackupClientsModal } from './features/backups/BackupClientsModal';
import { LogsPage } from './features/logs/LogsPage';
import { SSHKeysPanel } from './features/keys/SSHKeysPanel';
import { HelpPanel } from './features/help/HelpPanel';
import type {
  Action,
  Backup,
  DiscoveryChoice,
  InstallationReport,
  JobDetail,
  NodeRecord,
  InboundFinding,
  JobOptions,
  NodeSummary,
  Plan,
  SSHKey,
} from './types';

type ModalState =
  | { kind: 'node'; record: NodeRecord | null; template: string }
  | { kind: 'manage'; node: NodeSummary }
  | {
      kind: 'confirm';
      title: string;
      description: string;
      danger?: boolean;
      confirm: () => Promise<void>;
    }
  | { kind: 'create-key' }
  | { kind: 'key-result'; key: SSHKey }
  | { kind: 'assign-key'; keyId: string }
  | { kind: 'deployment'; record: NodeRecord; report: InstallationReport | null }
  | { kind: 'tunnel'; record: NodeRecord; report: InstallationReport }
  | { kind: 'pool'; record: NodeRecord; report: InstallationReport }
  | { kind: 'inbound'; record: NodeRecord; inbound: InboundFinding; remove: boolean }
  | { kind: 'client'; record: NodeRecord; inbound: InboundFinding; remove: boolean }
  | { kind: 'xhttp'; record: NodeRecord; report: InstallationReport; inbound?: InboundFinding; publish?: boolean }
  | { kind: 'discovery'; record: NodeRecord; job: JobDetail }
  | { kind: 'plan'; record: NodeRecord; action: Action; backupId: string | null; plan: Plan | null; options?: JobOptions }
  | { kind: 'import'; done?: (backup: Backup) => void }
  | { kind: 'restore'; backup: Backup }
  | { kind: 'backup-clients'; backup?: Backup; record?: NodeRecord; inbound?: InboundFinding; report?: InstallationReport };

function SimpleForm({
  title,
  description,
  fields,
  initial,
  busy,
  error,
  onClose,
  onSubmit,
  submit,
}: {
  title: string;
  description?: string;
  fields: FormField[];
  initial: FormValues;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (values: FormValues) => void;
  submit?: string;
}) {
  const [values, setValues] = useState(initial);
  return (
    <FormDialog
      title={title}
      description={description}
      fields={fields}
      values={values}
      onChange={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
      busy={busy}
      error={error}
      onClose={onClose}
      onSubmit={() => onSubmit(values)}
      submit={submit}
    />
  );
}

function ImportModal({
  busy,
  error,
  onClose,
  onImport,
}: {
  busy: boolean;
  error: string;
  onClose: () => void;
  onImport: (file: File) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  return (
    <Modal
      title="Загрузить бэкап"
      description="Файл базы SQLite 3x-ui (.db). После загрузки проверяются структура и целостность."
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!file}
            onClick={() => file && onImport(file)}
            icon={<Upload size={17} />}
          >
            Загрузить файл
          </Button>
        </>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      <label className="upload-zone">
        <Upload size={28} />
        <strong>{file ? file.name : 'Выбери файл .db'}</strong>
        <span>Файл останется в локальном разделе «Бэкапы»</span>
        <input
          type="file"
          aria-label="Файл бэкапа SQLite"
          accept=".db"
          disabled={busy}
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
      </label>
    </Modal>
  );
}

export default function App() {
  const w = useWorkspace();
  const nav = useWorkspaceRoute(w.dirty);
  const { route, navigate } = nav;
  const [modal, setModal] = useState<ModalState | null>(null);
  const [guide, setGuide] = useState('start');
  const [restoreChoice, setRestoreChoice] = useState<{ nodeId: string; backupId: string } | null>(
    null,
  );
  const nodeId = route.page === 'node' ? route.id : null;
  useEffect(() => w.selectNode(nodeId), [nodeId, w.selectNode]);
  const reportJob = useNodeReport(nodeId, w.jobs);
  const logId =
    route.page === 'logs'
      ? route.id || w.jobs.find(isRunning)?.id || w.jobs[0]?.id
      : route.page === 'operations'
        ? route.id
        : undefined;
  const detail = useJobDetail(logId);
  useEffect(() => {
    w.setError('');
    w.setNotice('');
  }, [route.page]);
  const closeModal = () => {
    if (!w.busy) {
      setModal(null);
      w.setError('');
    }
  };
  function showModal(value: ModalState) {
    w.setError('');
    setModal(value);
  }
  function requireSaved() {
    if (w.dirty) {
      w.setError('Сначала сохрани или отмени изменения YAML.');
      return false;
    }
    return true;
  }
  async function newNode() {
    if (!requireSaved() || w.busy) return;
    const result = await w.run(() => api<{ yaml: string }>('/template'));
    if (result) showModal({ kind: 'node', record: null, template: result.yaml });
  }
  function editNode() {
    if (!w.selected || !requireSaved()) return;
    showModal({ kind: 'node', record: w.selected, template: w.selected.yaml });
  }
  async function saveNode(text: string, expectedId?: string) {
    const record = await w.run(async () => {
      if (!expectedId) {
        const list = await api<NodeSummary[]>('/nodes');
        if (list.some((n) => n.id === readConfig(text).id))
          throw new Error('Нода с таким ID уже существует. Выбери другой ID.');
      }
      return w.saveNode(text, expectedId);
    });
    if (record) {
      setModal(null);
      if (!expectedId) navigate('/nodes/' + record.id);
    }
  }
  function manageNode(node: NodeSummary) {
    if (requireSaved()) showModal({ kind: 'manage', node: w.nodes.find((n) => n.id === node.id) || node });
  }
  async function stateNode(node: NodeSummary, state: 'active' | 'hidden' | 'archived') {
    const saved = await w.run(() => w.changeState(node.id, state));
    if (saved) setModal(null);
  }
  function deleteNode(node: NodeSummary) {
    showModal({
      kind: 'confirm',
      title: 'Удалить ноду из Nodekit?',
      description:
        'Настройки «' +
        node.name +
        '» будут удалены из локальной панели. VPS, бэкапы и история операций сохранятся.',
      danger: true,
      confirm: async () => {
        await api('/nodes/' + node.id, { method: 'DELETE' });
        await w.refresh();
        navigate('/nodes');
        w.setNotice('Нода удалена из локальной панели');
      },
    });
  }
  async function getRecord(job?: JobDetail) {
    return job ? api<NodeRecord>('/nodes/' + job.node_id) : w.selected;
  }
  async function configure(job?: JobDetail) {
    if (!requireSaved()) return;
    const record = await w.run(() => getRecord(job));
    if (!record) return;
    const config = readConfig(record.yaml);
    const inventory = job?.report || reportJob?.report || null;
    const matches =
      inventory?.ssh_host === config.ssh.host && inventory?.ssh_port === (config.ssh.port || 22);
    showModal({ kind: 'deployment', record, report: matches ? inventory : null });
  }
  async function suggest(job: JobDetail) {
    if (!job.report || !requireSaved()) return;
    const record = await w.run(async () => {
      const node = await api<NodeRecord>('/nodes/' + job.node_id);
      const config = readConfig(node.yaml);
      if (
        job.report?.ssh_host !== config.ssh.host ||
        job.report.ssh_port !== (config.ssh.port || 22)
      )
        throw new Error('Отчёт относится к другому SSH-адресу. Повтори обнаружение этой ноды.');
      return node;
    });
    if (record) showModal({ kind: 'discovery', record, job });
  }
  async function applySuggestions(choice: DiscoveryChoice) {
    if (modal?.kind !== 'discovery') return;
    const context = modal;
    const record = await w.run(async () => {
      const result = await api<{ yaml: string }>('/config/from-discovery', {
        method: 'POST',
        body: JSON.stringify({ yaml: context.record.yaml, job_id: context.job.id, ...choice }),
      });
      return w.saveNode(
        preserveDeploymentIntent(
          context.record.yaml,
          result.yaml,
          !context.job.report!.panels.length,
        ),
        context.record.id,
      );
    });
    if (record) setModal(null);
  }
  async function preview(record: NodeRecord, action: Action, backupId: string | null = null, options?: JobOptions) {
    if (!requireSaved()) return;
    showModal({ kind: 'plan', record, action, backupId, plan: null, options });
    const plan = await w.run(() => options ? api<Plan>('/nodes/' + record.id + '/plan', {
      method: 'POST', body: JSON.stringify({ action, revision: record.revision, ...(backupId ? { backup_id: backupId } : {}), ...options }),
    }) : api<Plan>('/nodes/' + record.id + '/plan?action=' + action));
    if (plan) setModal({ kind: 'plan', record, action, backupId, plan, options });
  }
  async function launch() {
    if (modal?.kind !== 'plan' || !modal.plan) return;
    const context = modal;
    const job = await w.run(async () => {
      const result = await api<JobDetail>('/nodes/' + context.record.id + '/jobs', {
        method: 'POST',
        body: JSON.stringify({
          action: context.action,
          revision: context.plan!.revision,
          backup_id: ['restore', 'client_import'].includes(context.action) ? context.backupId : null,
          ...context.options,
        }),
      });
      await w.refresh();
      return result;
    });
    if (job) {
      setModal(null);
      navigate('/operations/' + job.id);
    }
  }
  async function importBackup(file: File) {
    if (modal?.kind !== 'import') return;
    const done = modal.done;
    const backup = await w.run(async () => {
      const result = await api<Backup>('/backups?filename=' + encodeURIComponent(file.name), {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file,
      });
      await w.refresh();
      w.setNotice('Бэкап проверен и загружен');
      return result;
    });
    if (backup) {
      done?.(backup);
      setModal(null);
    }
  }
  function openImport(done?: (backup: Backup) => void) {
    showModal({ kind: 'import', done });
  }
  async function generateKey(name: string) {
    return w.run(async () => {
      const result = await api<SSHKey>('/ssh-keys', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });
      await w.refresh();
      return result;
    });
  }
  async function createKey(name: string) {
    const key = await generateKey(name);
    if (key) showModal({ kind: 'key-result', key });
  }
  function deleteKey(key: SSHKey) {
    showModal({
      kind: 'confirm',
      title: 'Удалить SSH-ключ?',
      description:
        'Локальная пара «' +
        key.name +
        '» будет удалена. Публичная часть в authorized_keys на VPS останется.',
      danger: true,
      confirm: async () => {
        await api('/ssh-keys/' + key.id, { method: 'DELETE' });
        await w.refresh();
        w.setNotice('SSH-ключ удалён из Nodekit');
      },
    });
  }
  async function assignKey(keyId: string, id: string) {
    const record = await w.run(async () => {
      const current = await api<NodeRecord>('/nodes/' + id);
      const result = await api<{ yaml: string }>('/config/ssh-key', {
        method: 'POST',
        body: JSON.stringify({ yaml: current.yaml, key_id: keyId }),
      });
      return w.saveNode(result.yaml, id);
    });
    if (record) setModal(null);
  }
  async function chooseRestore(backup: Backup, id: string) {
    const record = await w.run(() => api<NodeRecord>('/nodes/' + id));
    if (record) {
      setRestoreChoice({ nodeId: id, backupId: backup.id });
      await preview(record, 'restore', backup.id);
    }
  }
  const nodeOptions = [
    { value: '', label: 'Выбери ноду' },
    ...w.nodes.filter((n) => n.state !== 'archived').map((n) => ({ value: n.id, label: n.name })),
  ];

  function renderModal() {
    if (!modal) return null;
    const common = { busy: w.busy, error: w.error, onClose: closeModal };
    switch (modal.kind) {
      case 'node':
        return (
          <NodeFormModal
            {...common}
            record={modal.record}
            template={modal.template}
            nodes={w.nodes}
            keys={w.keys}
            onSave={saveNode}
            onCreateKey={generateKey}
          />
        );
      case 'deployment':
        return (
          <DeploymentModal
            {...common}
            record={modal.record}
            report={modal.report}
            onSave={async (text) => {
              const saved = await w.run(() => w.saveNode(text, modal.record.id));
              if (saved) {
                setModal(null);
                if (route.page === 'node' && route.tab === 'inbounds') await preview(saved, modal.report?.caddy_attachment === 'required' ? 'attach_caddy' : 'configure');
              }
            }}
          />
        );
      case 'pool':
        return <TunnelPoolModal {...common} record={modal.record} report={modal.report}
          onPreview={(options) => preview(modal.record, 'tunnel', null, options)} />;
      case 'tunnel':
        return <TunnelModal {...common} record={modal.record} report={modal.report}
          onPreview={(options) => preview(modal.record, 'tunnel', null, options)} />;
      case 'inbound':
        return <InboundModal {...common} record={modal.record} inbound={modal.inbound} remove={modal.remove}
          onPreview={(options) => preview(modal.record, 'inbound', null, options)} />;
      case 'xhttp':
        return <XHTTPModal {...common} record={modal.record} report={modal.report} inbound={modal.inbound} publish={modal.publish}
          onPreview={(options) => preview(modal.record, 'xhttp', null, options)} />;
      case 'client':
        return <ClientModal {...common} record={modal.record} inbound={modal.inbound} remove={modal.remove}
          onPreview={(options) => preview(modal.record, 'inbound', null, options)} />;
      case 'discovery':
        return (
          <DiscoveryModal
            {...common}
            record={modal.record}
            report={modal.job.report!}
            onSave={applySuggestions}
          />
        );
      case 'plan':
        return (
          <PlanModal
            {...common}
            record={modal.record}
            action={modal.action}
            plan={modal.plan}
            onReload={() => preview(modal.record, modal.action, modal.backupId, modal.options)}
            onLaunch={launch}
          />
        );
      case 'import':
        return <ImportModal {...common} onImport={importBackup} />;
      case 'create-key':
        return (
          <SimpleForm
            {...common}
            title="Создать SSH-ключ"
            description="Ed25519 без парольной фразы для фонового SSH. Приватная часть останется в локальном хранилище Nodekit."
            fields={[
              {
                name: 'name',
                label: 'Название ключа',
                required: true,
                maxLength: 80,
                placeholder: 'Например, доступ к EU-серверам',
              },
            ]}
            initial={{ name: '' }}
            onSubmit={(values) => createKey(String(values.name))}
            submit="Создать ключ"
          />
        );
      case 'key-result':
        return (
          <Modal
            title="SSH-ключ создан"
            description="Добавь публичную часть в authorized_keys на сервере."
            onClose={closeModal}
            footer={
              <Button
                variant="primary"
                onClick={() => showModal({ kind: 'assign-key', keyId: modal.key.id })}
              >
                Назначить ноде
              </Button>
            }
          >
            <CodeBlock value={modal.key.public_key} label="Публичный ключ" />
            <p className="mono muted">{modal.key.fingerprint}</p>
          </Modal>
        );
      case 'assign-key':
        return (
          <SimpleForm
            key={modal.keyId}
            {...common}
            title="Назначить SSH-ключ"
            fields={[
              { name: 'node', label: 'Нода', type: 'select', required: true, options: nodeOptions },
            ]}
            initial={{ node: '' }}
            onSubmit={(values) => assignKey(modal.keyId, String(values.node))}
            submit="Сохранить привязку"
          />
        );
      case 'backup-clients':
        return <BackupClientsModal
          {...common}
          backup={modal.backup}
          record={modal.record}
          inbound={modal.inbound}
          report={modal.report}
          nodes={w.nodes}
          backups={w.backups}
          jobs={w.jobs}
          onPreview={(node, selectedBackup, options) =>
            preview(node, 'client_import', selectedBackup.id, options)
          }
        />;
      case 'restore':
        return (
          <SimpleForm
            key={modal.backup.id}
            {...common}
            title="Восстановить из бэкапа"
            description={modal.backup.filename}
            fields={[
              {
                name: 'node',
                label: 'Целевая нода',
                type: 'select',
                required: true,
                options: nodeOptions,
              },
            ]}
            initial={{ node: '' }}
            onSubmit={(values) => chooseRestore(modal.backup, String(values.node))}
            submit="Посмотреть план"
          />
        );
      case 'confirm':
        return (
          <Modal
            title={modal.title}
            description={modal.description}
            onClose={closeModal}
            busy={w.busy}
            footer={
              <>
                <Button onClick={closeModal} disabled={w.busy}>
                  Отмена
                </Button>
                <Button
                  className={modal.danger ? 'danger-button' : ''}
                  variant="primary"
                  loading={w.busy}
                  onClick={async () => {
                    const success = await w.run(async () => {
                      await modal.confirm();
                      return true;
                    });
                    if (success) setModal(null);
                  }}
                >
                  Подтвердить
                </Button>
              </>
            }
          >
            {w.error && <Alert tone="error">{w.error}</Alert>}
          </Modal>
        );
      case 'manage':
        return (
          <NodeManagementModal
            {...common}
            node={modal.node}
            onState={(state) => stateNode(modal.node, state)}
            onDelete={() => deleteNode(modal.node)}
          />
        );
    }
  }
  let content;
  if (w.loading) content = <Loading label="Загрузка рабочего пространства…" />;
  else
    switch (route.page) {
      case 'dashboard':
        content = <DashboardPage workspace={w} navigate={navigate} onCreate={newNode} />;
        break;
      case 'nodes':
        content = (
          <NodesPage
            nodes={w.nodes}
            jobs={w.jobs}
            onOpen={(id) => navigate('/nodes/' + id)}
            onCreate={newNode}
            onManage={manageNode}
          />
        );
        break;
      case 'node':
        content = (
          <NodePage
            route={route}
            workspace={w}
            reportJob={reportJob}
            navigate={navigate}
            onEdit={editNode}
            onManage={() => w.selected && manageNode(w.selected)}
            onDeployment={() => configure()}
            onInbound={(inbound, remove) => {
              if (w.selected && requireSaved()) showModal({ kind: 'inbound', record: w.selected, inbound, remove });
            }}
            onPreparePool={async () => {
              if (!w.selected || !requireSaved()) return;
              const doc = parse(w.selected.yaml);
              if (!Array.isArray(doc.tunnels) || doc.tunnels.length !== 1) return;
              const base = doc.tunnels[0];
              const used = new Set([base.local_port, doc.panel?.port, doc.panel?.subscription_port,
                ...(doc.deployment?.inbounds || []).map((i: {port: number}) => i.port)]);
              const copies = [2, 3].map((i) => {
                let port = Number(base.local_port) + i - 1;
                while (used.has(port) && port < 65535) port++;
                if (port > 65535) throw new Error('Нет свободных локальных портов.');
                used.add(port);
                return { ...base, name: String(base.name) + '-' + i, local_port: port };
              });
              doc.tunnels.push(...copies);
              const saved = await w.run(() => w.saveNode(stringify(doc), w.selected!.id));
              if (saved) w.setNotice('В YAML сохранены 3 независимые SSH-сессии. Теперь выбери «Поднять пул».');
            }}
            onTunnelPool={() => {
              if (w.selected && reportJob?.report && requireSaved()) showModal({ kind: 'pool', record: w.selected, report: reportJob.report });
            }}
            onPublishXHTTP={(inbound) => {
              if (w.selected && reportJob?.report && requireSaved()) showModal({ kind: 'xhttp', record: w.selected, report: reportJob.report, inbound, publish: true });
            }}
            onXHTTP={(inbound) => {
              if (w.selected && reportJob?.report && requireSaved()) showModal({ kind: 'xhttp', record: w.selected, report: reportJob.report, inbound });
            }}
            onClient={(inbound, remove) => {
              if (w.selected && requireSaved()) showModal({ kind: 'client', record: w.selected, inbound, remove });
            }}
            onRestoreClients={(inbound) => {
              if (w.selected && reportJob?.report && requireSaved())
                showModal({ kind: 'backup-clients', record: w.selected, inbound, report: reportJob.report });
            }}
            onTunnel={() => {
              if (w.selected && reportJob?.report && requireSaved()) showModal({ kind: 'tunnel', record: w.selected, report: reportJob.report });
            }}
            onBenchmark={(network_benchmark) => {
              if (w.selected && requireSaved()) void preview(w.selected, 'network_benchmark', null, { network_benchmark });
            }}
            onTCPTuning={(algorithm, expected_fingerprint) => {
              if (w.selected && requireSaved())
                void preview(w.selected, 'tcp_tuning', null, { tcp_tuning: { algorithm, expected_fingerprint } });
            }}
            onTraffic={(inbound) => {
              if (w.selected) void preview(w.selected, 'traffic', null, { traffic: { id: inbound.id, expected_fingerprint: inbound.fingerprint! } });
            }}
            onSuggest={suggest}
            onPlan={(action, backupId) =>
              w.selected && preview(w.selected, action, backupId || null)
            }
            onImport={openImport}
            preferredBackup={
              restoreChoice?.nodeId === route.id ? restoreChoice.backupId : undefined
            }
          />
        );
        break;
      case 'operations':
        content = route.id ? (
          <OperationDetail
            job={detail.job}
            error={detail.error}
            nodes={w.nodes}
            navigate={navigate}
            onConfigure={configure}
            onSuggest={suggest}
          />
        ) : (
          <OperationsPage jobs={w.jobs} nodes={w.nodes} navigate={navigate} />
        );
        break;
      case 'subscriptions':
        content = (
          <SubscriptionsPage
            nodes={w.nodes}
            jobs={w.jobs}
            busy={w.busy}
            onDiscover={(record) => preview(record, 'check')}
            onPreview={(record, options) => preview(record, 'subscription_maintenance', null, options)}
            onClient={(record, inbound, remove) => {
              if (requireSaved()) showModal({ kind: 'client', record, inbound, remove });
            }}
            onRestoreClients={(record, inbound, report) => {
              if (requireSaved())
                showModal({ kind: 'backup-clients', record, inbound, report });
            }}
            onOpenJob={(id) => navigate('/operations/' + id)}
          />
        );
        break;
      case 'backups':
        content = (
          <BackupsPage
            backups={w.backups}
            onImport={() => openImport()}
            onRestore={(backup) => showModal({ kind: 'restore', backup })}
            onClients={(backup) => showModal({ kind: 'backup-clients', backup })}
          />
        );
        break;
      case 'logs':
        content = (
          <LogsPage
            jobs={w.jobs}
            nodes={w.nodes}
            job={detail.job}
            error={detail.error}
            navigate={navigate}
          />
        );
        break;
      case 'keys':
        content = (
          <SSHKeysPanel
            keys={w.keys}
            onCreate={() => showModal({ kind: 'create-key' })}
            onDelete={deleteKey}
            onUse={(keyId) => showModal({ kind: 'assign-key', keyId })}
            onHelp={() => {
              setGuide('ssh');
              navigate('/help');
            }}
          />
        );
        break;
      case 'help':
        content = (
          <HelpPanel selected={guide} onSelect={setGuide} onBack={() => navigate('/nodes')} />
        );
        break;
      default:
        content = (
          <EmptyState
            title="Страница не найдена"
            action={
              <Button onClick={() => navigate('/dashboard')} icon={<ArrowLeft size={17} />}>
                На главную
              </Button>
            }
          />
        );
    }
  return (
    <Shell route={route} nodes={w.nodes} online={w.online} navigate={navigate} onCreate={newNode}>
      {!modal && w.error && (
        <Alert tone="error" onClose={() => w.setError('')}>
          {w.error}
        </Alert>
      )}
      {w.notice && <Alert tone="success">{w.notice}</Alert>}
      {!w.loading && !w.online && (
        <div className="info-banner">
          Нет связи с локальным API. Данные могут быть устаревшими.
          <Button small onClick={() => w.run(w.refresh)}>
            Повторить
          </Button>
        </div>
      )}
      {content}
      {renderModal()}
      {nav.pending && (
        <Modal
          title="Отменить изменения?"
          description="В YAML есть несохранённые изменения. Они будут потеряны при переходе."
          onClose={nav.cancel}
          footer={
            <>
              <Button onClick={nav.cancel}>Продолжить редактирование</Button>
              <Button
                variant="primary"
                onClick={() => {
                  w.setYaml(w.selected?.yaml || '');
                  nav.discard();
                }}
              >
                Отменить и перейти
              </Button>
            </>
          }
        >
          {null}
        </Modal>
      )}
    </Shell>
  );
}
