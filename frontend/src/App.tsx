import { useEffect, useRef, useState } from 'react';
import { Activity, BookOpen, KeyRound, ArrowDownToLine, ArrowRight, Check, ChevronRight, Circle, Code2, Database, FileCode2, FolderOpen, Network, Play, Plus, Save, Server, ShieldCheck, Terminal, Upload, X } from 'lucide-react';
import { api, getErrorMessage } from './framework/api';
import { messages, formatMessage, statusLabel } from './framework/messages';
import { Alert, Button, CardHeader, IconButton, Spinner, StatusBadge } from './framework/components';
import type { Action, Backup, Job, JobDetail, NodeRecord, NodeSummary, Plan, DraftConfig, Installation, SSHKey } from './types';

import { SSHKeysPanel } from './features/keys/SSHKeysPanel';
import { HelpPanel } from './features/help/HelpPanel';
import { ConnectionSettings } from './features/nodes/ConnectionSettings';
import { getNodeErrorMessage } from './features/nodes/configErrors';
import { InstallationReportView } from './features/nodes/InstallationReportView';

const actions = (Object.keys(messages.action) as Action[]).map(id => ({ id, ...messages.action[id] }));
const actionTitle = (action: Action) => messages.action[action].title;
const active = (job: Job) => ['queued', 'running'].includes(job.status);
const date = (value: string) => new Date(value.replace(' ', 'T') + 'Z').toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export default function App() {
  const [view, setView] = useState<'nodes' | 'keys' | 'help'>('nodes');
  const [guide, setGuide] = useState('start');
  const [keys, setKeys] = useState<SSHKey[]>([]);
  const [draft, setDraft] = useState<DraftConfig | null>(null);
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [selected, setSelected] = useState<NodeRecord | null>(null);
  const [text, setText] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [backupId, setBackupId] = useState('');
  const [action, setAction] = useState<Action>('check');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [file, setFile] = useState('compose.yaml');
  const [tab, setTab] = useState<'yaml' | 'files'>('yaml');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const terminal = useRef<HTMLDivElement>(null);
  const dirty = !selected || text !== selected.yaml;
  const running = jobs.some(active);
  const showingFiles = tab === 'files' && !!plan && !!Object.keys(plan.files).length;

  async function refreshKeys() { setKeys(await api<SSHKey[]>('/ssh-keys')); }
  function openHelp(id = 'start') { setGuide(id); setView('help'); }

  useEffect(() => {
    const controller = new AbortController();
    setDraft(null);
    const timer = setTimeout(() => {
      api<{ node: DraftConfig }>('/config/validate', { method: 'POST', body: JSON.stringify({ yaml: text }), signal: controller.signal })
        .then(result => { if (!controller.signal.aborted) setDraft(result.node); })
        .catch(() => { /* The editor stays usable while YAML is incomplete. */ });
    }, 350);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [text]);

  useEffect(() => {
    if (draft && draft.panel.installation !== 'managed' && ['fresh', 'restore'].includes(action)) {
      setAction('check'); setPlan(null);
    }
  }, [draft, action]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<NodeSummary[]>('/nodes'), api<{ yaml: string }>('/template'), api<SSHKey[]>('/ssh-keys')])
      .then(async ([list, template, savedKeys]) => {
        if (cancelled) return;
        setNodes(list); setKeys(savedKeys);
        if (list.length) {
          const record = await api<NodeRecord>(`/nodes/${list[0].id}`);
          if (!cancelled) { setSelected(record); setText(record.yaml); }
        } else setText(template.yaml);
      }).catch(err => !cancelled && setError(getErrorMessage(err)));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const [list, snapshots] = await Promise.all([api<Job[]>('/jobs'), api<Backup[]>('/backups')]);
        if (!cancelled) { setJobs(list); setBackups(snapshots); setOnline(true); }
      } catch { if (!cancelled) setOnline(false); }
    };
    void poll();
    const timer = setInterval(poll, 2500);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await api<JobDetail>(`/jobs/${jobId}`);
        if (!cancelled) setJob(detail);
      } catch (err) { if (!cancelled) setError(getErrorMessage(err)); }
    };
    void poll();
    const timer = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [jobId]);

  useEffect(() => { terminal.current?.scrollTo({ top: terminal.current.scrollHeight, behavior: 'smooth' }); }, [job?.events.length]);

  async function perform(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError(getNodeErrorMessage(err)); }
    finally { setBusy(false); }
  }
  async function chooseNode(id: string) {
    setView('nodes');
    if (dirty && selected && !window.confirm(messages.confirm.discardForNode)) return;
    await perform(async () => {
      const record = await api<NodeRecord>(`/nodes/${id}`);
      setSelected(record); setText(record.yaml); setPlan(null); setTab('yaml');
    });
  }
  async function newNode() {
    setView('nodes');
    if (dirty && selected && !window.confirm(messages.confirm.discardForNew)) return;
    await perform(async () => {
      const template = await api<{ yaml: string }>('/template');
      setSelected(null); setText(template.yaml.replace('moscow-1', `node-${nodes.length + 1}`)); setPlan(null); setTab('yaml');
    });
  }
  async function save() {
    await perform(async () => {
      const validated = await api<{ node: { id: string } }>('/config/validate', { method: 'POST', body: JSON.stringify({ yaml: text }) });
      const record = await api<NodeRecord>(`/nodes/${validated.node.id}`, { method: 'PUT', body: JSON.stringify({ yaml: text }) });
      setSelected(record); setNodes(await api<NodeSummary[]>('/nodes')); setPlan(null); setNotice(messages.notice.configSaved);
    });
  }
  async function preview() {
    if (!selected) return;
    await perform(async () => {
      const result = await api<Plan>(`/nodes/${selected.id}/plan?action=${action}`);
      setPlan(result); setFile(Object.keys(result.files)[0] || '');
    });
  }
  async function launch() {
    if (!selected || !plan) return;
    await perform(async () => {
      const result = await api<JobDetail>(`/nodes/${selected.id}/jobs`, { method: 'POST', body: JSON.stringify({ action: plan.action, revision: plan.revision, backup_id: plan.action === 'restore' ? backupId : null }) });
      setJobId(result.id); setJob(result); setJobs(await api<Job[]>('/jobs')); setPlan(null);
      setNotice(messages.notice.jobStarted);
    });
  }
  async function importBackup(file: File) {
    await perform(async () => {
      const result = await api<Backup>(`/backups?filename=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      setBackups(await api<Backup[]>('/backups')); setBackupId(result.id); setNotice(messages.notice.backupImported);
    });
  }

  async function selectKey(id: string) {
    await perform(async () => {
      const result = await api<{ yaml: string }>('/config/ssh-key', { method: 'POST', body: JSON.stringify({ yaml: text, key_id: id || null }) });
      setText(result.yaml); setPlan(null); setNotice(messages.connection.changed); setView('nodes');
    });
  }
  async function selectInstallation(installation: Installation) {
    await perform(async () => {
      const result = await api<{ yaml: string }>('/config/installation', { method: 'POST', body: JSON.stringify({ yaml: text, installation }) });
      setText(result.yaml); setPlan(null); setNotice(messages.connection.changed);
    });
  }

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="OMSI Nodekit"><span className="brand-icon"><Network size={23}/></span><span>omsi<span className="brand-light"> / nodekit</span></span></a>
      <div className="workspace-label">{messages.ui.workspace} <span>v0.1</span></div>
      <nav className="workspace-nav" aria-label={messages.navigation.label}>
        <button type="button" className={`nav-item ${view === 'nodes' ? 'selected' : ''}`} aria-current={view === 'nodes' ? 'page' : undefined} onClick={() => setView('nodes')}><Server size={17}/>{messages.navigation.nodes}<span className="count">{nodes.length}</span></button>
        <button type="button" className={`nav-item ${view === 'keys' ? 'selected' : ''}`} aria-current={view === 'keys' ? 'page' : undefined} onClick={() => setView('keys')}><KeyRound size={17}/>{messages.navigation.keys}<span className="count">{keys.length}</span></button>
        <button type="button" className={`nav-item ${view === 'help' ? 'selected' : ''}`} aria-current={view === 'help' ? 'page' : undefined} onClick={() => openHelp()}><BookOpen size={17}/>{messages.navigation.help}</button>
      </nav>
      <div className="node-section"><span>{messages.ui.myNodes}</span><IconButton label={messages.ui.newNode} onClick={newNode} disabled={busy}><Plus size={17}/></IconButton></div>
      <div className="node-list">{nodes.length ? nodes.map(node => <button key={node.id} className={`node-item ${selected?.id === node.id ? 'current' : ''}`} onClick={() => chooseNode(node.id)}><span className="node-avatar">{node.id.slice(0, 2).toUpperCase()}</span><span className="node-caption"><strong>{node.name}</strong><small>{node.id}</small></span><ChevronRight size={14}/></button>) : <div className="sidebar-empty">{messages.ui.emptyNodesTitle}<br/>{messages.ui.emptyNodesBody}</div>}</div>
      <div className="sidebar-note"><ShieldCheck size={19}/><div><strong>{messages.ui.localControlTitle}</strong><p>{messages.ui.localControlBody}<br/>{messages.ui.sshConnection}</p></div></div>
      <div className="backend-state"><span className={`dot ${online ? 'green' : ''}`}/>{online ? messages.ui.online : messages.ui.offline}<span>127.0.0.1</span></div>
    </aside>
    <main>
      <header className="topbar"><span>{messages.ui.infrastructure} <ChevronRight size={13}/> {messages.navigation[view]}</span><span className="local-badge"><span className="dot green"/> {messages.ui.localWorkspace}</span></header>
      <div className="page-content">
        {error && <Alert tone="error" onClose={() => setError('')}>{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        {view === 'keys' ? <SSHKeysPanel keys={keys} refresh={refreshKeys} onUse={selectKey} onHelp={() => openHelp('ssh')}/>
          : view === 'help' ? <HelpPanel selected={guide} onSelect={setGuide} onBack={() => setView('nodes')}/>
          : <>
        <div className="page-heading"><div><div className="eyebrow">{messages.ui.slogan}</div><h1>{messages.ui.title}</h1><p>{messages.ui.subtitle}</p></div><Button onClick={newNode} disabled={busy} icon={<Plus size={16}/>}>{messages.ui.addNode}</Button></div>
        <section className="metrics" aria-label={messages.ui.statistics}><div><Server size={19}/><span>{messages.ui.nodeCount}</span><strong>{nodes.length.toString().padStart(2, '0')}</strong></div><div><Activity size={19}/><span>{messages.ui.activeJobs}</span><strong>{jobs.filter(active).length.toString().padStart(2, '0')}</strong></div><div><Database size={19}/><span>{messages.ui.backupCount}</span><strong>{backups.length.toString().padStart(2, '0')}</strong></div><div><Check size={19}/><span>{messages.ui.completedJobs}</span><strong>{jobs.filter(j => j.status === 'succeeded').length.toString().padStart(2, '0')}</strong></div></section>
        <div className="work-grid">
          <section className="card config-card"><CardHeader title={selected?.name || messages.ui.newNode} subtitle={selected?.id || messages.ui.newNodeHelp} icon={<FileCode2 size={18}/>} trailing={<StatusBadge tone={dirty ? 'amber' : 'mint'}>{dirty ? messages.ui.unsaved : messages.ui.saved}</StatusBadge>}/>
            <ConnectionSettings draft={draft} keys={keys} busy={busy} onKey={selectKey} onInstallation={selectInstallation} onManage={() => setView('keys')} onHelp={() => openHelp()}/>
            <div className="editor-tabs"><button className={!showingFiles ? 'chosen' : ''} onClick={() => setTab('yaml')}><Code2 size={14}/> node.yaml</button><button className={showingFiles ? 'chosen' : ''} onClick={() => setTab('files')} disabled={!plan || !Object.keys(plan.files).length}><FolderOpen size={14}/> {messages.ui.planFiles}</button><span>YAML</span></div>
            {!showingFiles ? <textarea className="yaml-editor" disabled={busy} aria-label={messages.ui.yamlLabel} value={text} onChange={event => { setText(event.target.value); setPlan(null); }} spellCheck={false}/> : <div className="files-preview"><div className="file-tabs">{plan && Object.keys(plan.files).map(name => <button key={name} className={file === name ? 'chosen' : ''} onClick={() => setFile(name)}>{name}</button>)}</div><pre>{plan?.files[file]}</pre></div>}
            <div className="editor-footer"><span><Circle size={9}/> {messages.ui.validationHint}</span><Button small onClick={save} disabled={busy || !dirty} icon={<Save size={14}/>}>{messages.ui.save}</Button></div>
          </section>
          <section className="card operations-card"><CardHeader title={messages.ui.operations} subtitle={messages.ui.operationsHint} icon={<Play size={17}/>}/>
            <div className="action-list">{actions.map(item => <button key={item.id} className={`action-option ${action === item.id ? 'active' : ''}`} onClick={() => { setAction(item.id); setPlan(null); }} disabled={busy || (!!draft && draft.panel.installation !== 'managed' && ['fresh', 'restore'].includes(item.id))}><span className="radio">{action === item.id && <span/>}</span><span><strong>{item.title}</strong><small>{item.description}</small></span>{action === item.id && <ArrowRight size={16}/>}</button>)}</div>
            {action === 'restore' && <div className="backup-picker"><label htmlFor="backup">{messages.ui.restoreBackup}</label><select id="backup" value={backupId} onChange={e => setBackupId(e.target.value)}><option value="">{messages.ui.selectBackup}</option>{backups.map(backup => <option key={backup.id} value={backup.id}>{backup.filename} · {backup.id.slice(0, 6)}</option>)}</select><Button variant="text" onClick={() => upload.current?.click()} disabled={busy} icon={<Upload size={14}/>}>{messages.ui.uploadBackup}</Button></div>}
            <input ref={upload} type="file" accept=".db" hidden onChange={event => { const picked = event.target.files?.[0]; if (picked) void importBackup(picked); event.target.value = ''; }}/>
            <div className="operation-bottom"><p><ShieldCheck size={15}/>{dirty ? messages.ui.saveFirst : messages.ui.previewHint}</p><Button variant="primary" full loading={busy} onClick={preview} disabled={dirty || running || (action === 'restore' && !backupId)} icon={<Play size={15}/>}>{messages.ui.preview}<ArrowRight size={15}/></Button></div>
          </section>
        </div>
        {plan && <section className="card plan-card"><div className="plan-heading"><div><div className="eyebrow">{messages.ui.previewTitle}</div><h2>{actionTitle(plan.action)}</h2><p>{plan.remote_dir}</p></div><IconButton label={messages.ui.closePlan} onClick={() => setPlan(null)}><X size={18}/></IconButton></div><ol>{plan.steps.map(step => <li key={step}>{step}</li>)}</ol>{['fresh', 'restore'].includes(plan.action) && <p className="plan-warning">{messages.ui.deploymentHint}</p>}<div className="plan-footer"><Button variant="text" onClick={() => setTab('files')} disabled={!Object.keys(plan.files).length} icon={<FileCode2 size={15}/>}>{messages.ui.inspectFiles}</Button><Button variant="primary" loading={busy} onClick={launch} disabled={dirty || running} icon={<Play size={15}/>}>{formatMessage(messages.ui.launch, { action: actionTitle(plan.action).toLowerCase() })}</Button></div></section>}
        <section className="card journal-card"><CardHeader title={messages.ui.journal} subtitle={messages.ui.journalHint} icon={<Terminal size={18}/>} trailing={<span className="journal-live"><span className={`dot ${running ? 'green' : ''}`}/>{running ? messages.ui.running : messages.ui.idle}</span>}/><div className="journal-body"><div className="job-list">{jobs.length ? jobs.map(item => <button key={item.id} className={`job-row ${jobId === item.id ? 'current' : ''}`} onClick={() => { setJobId(item.id); setJob(null); }}><span className={`status-icon ${item.status}`}>{active(item) ? <Spinner size={15}/> : item.status === 'succeeded' ? <Check size={15}/> : <X size={15}/>}</span><span><strong>{actionTitle(item.action)}</strong><small>{item.node_id} · {date(item.created_at)}</small></span><span className={`job-status ${item.status}`}>{statusLabel(item.status)}</span></button>) : <div className="empty-jobs"><Activity size={22}/><strong>{messages.ui.emptyJobs}</strong><p>{messages.ui.emptyJobsHint}</p></div>}</div><div className="terminal" ref={terminal} aria-label={messages.ui.taskJournal} aria-live="polite"><div className="terminal-caption"><span className="terminal-dots"><i/><i/><i/></span><span>{job ? `${job.node_id} / ${job.action}` : messages.ui.terminalReady}</span></div>{job ? <><div className="terminal-line dim">$ {job.action} · {job.id.slice(0, 8)}</div>{job.events.map(event => <div key={event.seq} className={`terminal-line ${event.level}`}><span>{date(event.created_at)}</span>{event.message}</div>)}{active(job) && <div className="terminal-line dim"><Spinner size={13}/> {messages.ui.waitForVps}</div>}{job.backup_id && <a className="download-link" href={`/api/backups/${job.backup_id}/download`}><ArrowDownToLine size={14}/> {messages.ui.downloadBackup}</a>}</> : <div className="terminal-placeholder"><span className="terminal-prompt">›</span> {messages.ui.terminalEmpty}<br/><span>{messages.ui.terminalHint}</span></div>}</div></div></section>
        {job?.report && <InstallationReportView report={job.report} node={job.node_id}/>}
        {!!backups.length && <section className="backups-section"><h2><Database size={17}/> {messages.ui.backups}</h2><div className="backup-items">{backups.map(backup => <a key={backup.id} className="backup-item" href={`/api/backups/${backup.id}/download`}><Database size={17}/><span><strong>{backup.filename}</strong><small>{formatMessage(messages.ui.backupSize, { size: (backup.size / 1024).toFixed(0) })} · SHA256 {backup.sha256.slice(0, 10)}…</small></span><ArrowDownToLine size={16}/></a>)}</div></section>}
        <footer className="page-footer"><span>OMSI NODEKIT <span> / </span> {messages.ui.footer}</span><span>{messages.ui.trafficHint}</span></footer>
        </>}
      </div>
    </main>
  </div>;
}
