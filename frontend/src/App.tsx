import { useEffect, useRef, useState } from 'react';
import { Activity, ArrowDownToLine, ArrowRight, Check, ChevronRight, Circle, Code2, Database, FileCode2, FolderOpen, LoaderCircle, Network, Play, Plus, Save, Server, ShieldCheck, Terminal, Upload, X } from 'lucide-react';
import { api, type Action, type Backup, type Job, type JobDetail, type NodeRecord, type NodeSummary, type Plan } from './api';

const actions: { id: Action; title: string; description: string }[] = [
  { id: 'check', title: 'Проверить окружение', description: 'SSH, Docker, Compose и systemd' },
  { id: 'fresh', title: 'Развернуть с нуля', description: 'Новая пустая панель и туннели' },
  { id: 'restore', title: 'Восстановить из БД', description: 'Сохранить клиентов, ключи и маршруты' },
  { id: 'doctor', title: 'Диагностика', description: 'Панель, туннели и тест трафика' },
  { id: 'backup', title: 'Скачать бэкап', description: 'Согласованный снимок SQLite' },
];
const actionTitle = (action: Action) => actions.find(item => item.id === action)!.title;
const statusText: Record<string, string> = { queued: 'В очереди', running: 'Выполняется', succeeded: 'Готово', failed: 'Ошибка', interrupted: 'Прервано' };
const active = (job: Job) => ['queued', 'running'].includes(job.status);
const date = (value: string) => new Date(value.replace(' ', 'T') + 'Z').toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export default function App() {
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
  const showingFiles = tab === 'files' && !!plan;

  useEffect(() => {
    let cancelled = false;
    Promise.all([api<NodeSummary[]>('/nodes'), api<{ yaml: string }>('/template')])
      .then(async ([list, template]) => {
        if (cancelled) return;
        setNodes(list);
        if (list.length) {
          const record = await api<NodeRecord>(`/nodes/${list[0].id}`);
          if (!cancelled) { setSelected(record); setText(record.yaml); }
        } else setText(template.yaml);
      }).catch(err => !cancelled && setError(String(err.message)));
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
      } catch (err) { if (!cancelled) setError((err as Error).message); }
    };
    void poll();
    const timer = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [jobId]);

  useEffect(() => { terminal.current?.scrollTo({ top: terminal.current.scrollHeight, behavior: 'smooth' }); }, [job?.events.length]);

  async function perform(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function chooseNode(id: string) {
    if (dirty && selected && !window.confirm('Перейти к другой ноде и отменить несохранённые изменения?')) return;
    await perform(async () => {
      const record = await api<NodeRecord>(`/nodes/${id}`);
      setSelected(record); setText(record.yaml); setPlan(null); setTab('yaml');
    });
  }
  async function newNode() {
    if (dirty && selected && !window.confirm('Создать ноду и отменить несохранённые изменения?')) return;
    await perform(async () => {
      const template = await api<{ yaml: string }>('/template');
      setSelected(null); setText(template.yaml.replace('moscow-1', `node-${nodes.length + 1}`)); setPlan(null); setTab('yaml');
    });
  }
  async function save() {
    await perform(async () => {
      const validated = await api<{ node: { id: string } }>('/config/validate', { method: 'POST', body: JSON.stringify({ yaml: text }) });
      const record = await api<NodeRecord>(`/nodes/${validated.node.id}`, { method: 'PUT', body: JSON.stringify({ yaml: text }) });
      setSelected(record); setNodes(await api<NodeSummary[]>('/nodes')); setPlan(null); setNotice('Конфигурация проверена и сохранена');
    });
  }
  async function preview() {
    if (!selected) return;
    await perform(async () => {
      const result = await api<Plan>(`/nodes/${selected.id}/plan?action=${action}`);
      setPlan(result); setFile('compose.yaml');
    });
  }
  async function launch() {
    if (!selected || !plan) return;
    await perform(async () => {
      const result = await api<JobDetail>(`/nodes/${selected.id}/jobs`, { method: 'POST', body: JSON.stringify({ action: plan.action, revision: plan.revision, backup_id: plan.action === 'restore' ? backupId : null }) });
      setJobId(result.id); setJob(result); setJobs(await api<Job[]>('/jobs')); setPlan(null);
      setNotice('Задача запущена. Ход выполнения — в журнале ниже.');
    });
  }
  async function importBackup(file: File) {
    await perform(async () => {
      const result = await api<Backup>(`/backups?filename=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      setBackups(await api<Backup[]>('/backups')); setBackupId(result.id); setNotice('Снимок SQLite проверен и добавлен');
    });
  }

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="OMSI Nodekit"><span className="brand-icon"><Network size={23}/></span><span>omsi<span className="brand-light"> / nodekit</span></span></a>
      <div className="workspace-label">ЛОКАЛЬНОЕ ПРОСТРАНСТВО <span>v0.1</span></div>
      <div className="nav-item selected"><Server size={17}/> Ноды <span className="count">{nodes.length}</span></div>
      <div className="node-section"><span>МОИ НОДЫ</span><button className="icon-button" onClick={newNode} disabled={busy} title="Новая нода" aria-label="Новая нода"><Plus size={17}/></button></div>
      <div className="node-list">{nodes.length ? nodes.map(node => <button key={node.id} className={`node-item ${selected?.id === node.id ? 'current' : ''}`} onClick={() => chooseNode(node.id)}><span className="node-avatar">{node.id.slice(0, 2).toUpperCase()}</span><span className="node-caption"><strong>{node.name}</strong><small>{node.id}</small></span><ChevronRight size={14}/></button>) : <div className="sidebar-empty">Добавь первую ноду.<br/>Её настройки останутся здесь.</div>}</div>
      <div className="sidebar-note"><ShieldCheck size={19}/><div><strong>Всё под твоим контролем</strong><p>Локальная панель.<br/>Подключение к VPS по SSH.</p></div></div>
      <div className="backend-state"><span className={`dot ${online ? 'green' : ''}`}/>{online ? 'Backend подключён' : 'Нет связи с backend'}<span>127.0.0.1</span></div>
    </aside>
    <main>
      <header className="topbar"><span>Инфраструктура <ChevronRight size={13}/> Ноды</span><span className="local-badge"><span className="dot green"/> LOCAL WORKSPACE</span></header>
      <div className="page-content">
        <div className="page-heading"><div><div className="eyebrow">МЕНЬШЕ РУТИНЫ. БОЛЬШЕ КОНТРОЛЯ.</div><h1>Твои ноды. Один пульт.</h1><p>Разворачивай, восстанавливай и проверяй — по одному конфигу.</p></div><button className="button secondary" onClick={newNode} disabled={busy}><Plus size={16}/> Добавить ноду</button></div>
        <section className="metrics" aria-label="Статистика"><div><Server size={19}/><span>Нод в конфигурации</span><strong>{nodes.length.toString().padStart(2, '0')}</strong></div><div><Activity size={19}/><span>Активных задач</span><strong>{jobs.filter(active).length.toString().padStart(2, '0')}</strong></div><div><Database size={19}/><span>Снимков базы</span><strong>{backups.length.toString().padStart(2, '0')}</strong></div><div><Check size={19}/><span>Успешных задач*</span><strong>{jobs.filter(j => j.status === 'succeeded').length.toString().padStart(2, '0')}</strong></div></section>
        {error && <div className="alert error" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Закрыть ошибку"><X size={16}/></button></div>}
        {notice && <div className="alert success" role="status"><Check size={16}/>{notice}</div>}
        <div className="work-grid">
          <section className="card config-card"><div className="card-heading"><div><span className="section-icon"><FileCode2 size={18}/></span><div><h2>{selected?.name || 'Новая нода'}</h2><p>{selected?.id || 'Начни с YAML-конфигурации'}</p></div></div><span className={`pill ${dirty ? 'amber' : 'mint'}`}>{dirty ? 'Не сохранено' : 'Сохранено'}</span></div>
            <div className="editor-tabs"><button className={!showingFiles ? 'chosen' : ''} onClick={() => setTab('yaml')}><Code2 size={14}/> node.yaml</button><button className={showingFiles ? 'chosen' : ''} onClick={() => setTab('files')} disabled={!plan}><FolderOpen size={14}/> Файлы плана</button><span>YAML</span></div>
            {!showingFiles ? <textarea className="yaml-editor" aria-label="YAML конфигурация ноды" value={text} onChange={event => { setText(event.target.value); setPlan(null); }} spellCheck={false}/> : <div className="files-preview"><div className="file-tabs">{plan && Object.keys(plan.files).map(name => <button key={name} className={file === name ? 'chosen' : ''} onClick={() => setFile(name)}>{name}</button>)}</div><pre>{plan?.files[file]}</pre></div>}
            <div className="editor-footer"><span><Circle size={9}/> Конфиг проверяется перед сохранением</span><button className="button secondary small" onClick={save} disabled={busy || !dirty}><Save size={14}/> Сохранить</button></div>
          </section>
          <section className="card operations-card"><div className="card-heading"><div><span className="section-icon"><Play size={17}/></span><div><h2>Операции</h2><p>Выбери следующий шаг</p></div></div></div>
            <div className="action-list">{actions.map(item => <button key={item.id} className={`action-option ${action === item.id ? 'active' : ''}`} onClick={() => { setAction(item.id); setPlan(null); }} disabled={busy}><span className="radio">{action === item.id && <span/>}</span><span><strong>{item.title}</strong><small>{item.description}</small></span>{action === item.id && <ArrowRight size={16}/>}</button>)}</div>
            {action === 'restore' && <div className="backup-picker"><label htmlFor="backup">Снимок для восстановления</label><select id="backup" value={backupId} onChange={e => setBackupId(e.target.value)}><option value="">Выбери .db файл</option>{backups.map(backup => <option key={backup.id} value={backup.id}>{backup.filename} · {backup.id.slice(0, 6)}</option>)}</select><button className="text-button" onClick={() => upload.current?.click()} disabled={busy}><Upload size={14}/> Загрузить SQLite .db</button></div>}
            <input ref={upload} type="file" accept=".db" hidden onChange={event => { const picked = event.target.files?.[0]; if (picked) void importBackup(picked); event.target.value = ''; }}/>
            <div className="operation-bottom"><p><ShieldCheck size={15}/>{dirty ? 'Сначала сохрани конфигурацию.' : 'Перед запуском покажем план и файлы.'}</p><button className="button primary full" onClick={preview} disabled={busy || dirty || running || (action === 'restore' && !backupId)}>{busy ? <LoaderCircle size={16} className="spin"/> : <Play size={15}/>} Показать план <ArrowRight size={15}/></button></div>
          </section>
        </div>
        {plan && <section className="card plan-card"><div className="plan-heading"><div><div className="eyebrow">ПРЕДВАРИТЕЛЬНЫЙ ПЛАН</div><h2>{actionTitle(plan.action)}</h2><p>{plan.remote_dir}</p></div><button className="icon-button" onClick={() => setPlan(null)} aria-label="Закрыть план"><X size={18}/></button></div><ol>{plan.steps.map(step => <li key={step}>{step}</li>)}</ol>{['fresh', 'restore'].includes(plan.action) && <p className="plan-warning">Только новая нода и пустой каталог. Клиенты и маршруты восстанавливаются из БД; чистая панель будет пустой. Внешние сертификаты и SSH-ключи подготовь отдельно.</p>}<div className="plan-footer"><button className="text-button" onClick={() => setTab('files')}><FileCode2 size={15}/> Посмотреть создаваемые файлы</button><button className="button primary" onClick={launch} disabled={busy || dirty || running}>{busy ? <LoaderCircle size={15} className="spin"/> : <Play size={15}/>} Запустить {actionTitle(plan.action).toLowerCase()}</button></div></section>}
        <section className="card journal-card"><div className="card-heading"><div><span className="section-icon"><Terminal size={18}/></span><div><h2>Журнал операций</h2><p>Реальный вывод задач, без догадок</p></div></div><span className="journal-live"><span className={`dot ${running ? 'green' : ''}`}/>{running ? 'ВЫПОЛНЯЕТСЯ' : 'ОЖИДАНИЕ'}</span></div><div className="journal-body"><div className="job-list">{jobs.length ? jobs.map(item => <button key={item.id} className={`job-row ${jobId === item.id ? 'current' : ''}`} onClick={() => { setJobId(item.id); setJob(null); }}><span className={`status-icon ${item.status}`}>{active(item) ? <LoaderCircle size={15} className="spin"/> : item.status === 'succeeded' ? <Check size={15}/> : <X size={15}/>}</span><span><strong>{actionTitle(item.action)}</strong><small>{item.node_id} · {date(item.created_at)}</small></span><span className={`job-status ${item.status}`}>{statusText[item.status]}</span></button>) : <div className="empty-jobs"><Activity size={22}/><strong>Пока без задач</strong><p>Начни с проверки окружения</p></div>}</div><div className="terminal" ref={terminal} aria-label="Журнал задачи" aria-live="polite"><div className="terminal-caption"><span className="terminal-dots"><i/><i/><i/></span><span>{job ? `${job.node_id} / ${job.action}` : 'nodekit — ready'}</span></div>{job ? <><div className="terminal-line dim">$ {job.action} · {job.id.slice(0, 8)}</div>{job.events.map(event => <div key={event.seq} className={`terminal-line ${event.level}`}><span>{date(event.created_at)}</span>{event.message}</div>)}{active(job) && <div className="terminal-line dim"><LoaderCircle size={13} className="spin"/> Ожидаем ответ VPS…</div>}{job.backup_id && <a className="download-link" href={`/api/backups/${job.backup_id}/download`}><ArrowDownToLine size={14}/> Скачать снимок БД</a>}</> : <div className="terminal-placeholder"><span className="terminal-prompt">›</span> Здесь появится ход выполнения.<br/><span>Выбери операцию и запусти её из панели.</span></div>}</div></div></section>
        {!!backups.length && <section className="backups-section"><h2><Database size={17}/> Бэкапы SQLite</h2><div className="backup-items">{backups.map(backup => <a key={backup.id} className="backup-item" href={`/api/backups/${backup.id}/download`}><Database size={17}/><span><strong>{backup.filename}</strong><small>{(backup.size / 1024).toFixed(0)} КБ · SHA256 {backup.sha256.slice(0, 10)}…</small></span><ArrowDownToLine size={16}/></a>)}</div></section>}
        <footer className="page-footer"><span>OMSI NODEKIT <span> / </span> СДЕЛАНО ДЛЯ СПОКОЙНЫХ ВЕЧЕРОВ</span><span>* По журналу задач · Статус VPN требует проверки трафика</span></footer>
      </div>
    </main>
  </div>;
}
