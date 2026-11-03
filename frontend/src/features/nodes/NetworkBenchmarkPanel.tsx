import { useEffect, useState } from 'react';
import type { BenchmarkProfile, BenchmarkReport, Job, JobDetail } from '../../types';
import { api } from '../../api';
import { Button } from '../../framework/components';
import { formatDate } from '../../app/format';

const defaults: BenchmarkProfile = { url: '', attempts: 3, sample_bytes: 16 * 1024 * 1024,
  min_mbps: 100, max_rtt_ms: 100, max_jitter_ms: 20, max_loss_percent: 1 };
const fields = [ ['min_mbps', 'Скорость ≥, Мбит/с'], ['max_rtt_ms', 'RTT ≤, мс'],
  ['max_jitter_ms', 'Разброс RTT ≤, мс'], ['max_loss_percent', 'Потери ICMP ≤, %'] ] as const;
const rows = [ ['mbps', 'HTTPS, Мбит/с'], ['rtt_ms', 'RTT, мс'], ['jitter_ms', 'Разброс RTT, мс'],
  ['loss_percent', 'Потери ICMP, %'] ];

export function comparable(a: BenchmarkReport, b: BenchmarkReport) {
  return a.scope === b.scope && JSON.stringify(a.profile) === JSON.stringify(b.profile)
    && JSON.stringify(a.resolved_addresses) === JSON.stringify(b.resolved_addresses);
}

export function BenchmarkComparison({ reports }: { reports: BenchmarkReport[] }) {
  const latest = reports[0];
  if (!latest) return <p>Сохранённых замеров пока нет.</p>;
  const previous = reports[1];
  const same = previous && comparable(latest, previous);
  return <>
    <p>{formatDate(latest.observed_at)} · {latest.algorithm?.toUpperCase() || 'Алгоритм неизвестен'} · {latest.samples.length}/{latest.profile.attempts} HTTPS-проб</p>
    {previous && !same && <p className="report-warning">Предыдущий замер сделан с другим профилем или DNS-адресами. Сравнение до/после недоступно.</p>}
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Метрика</th><th>Сейчас</th><th>Статус</th>{same && <th>Ранее · {previous.algorithm?.toUpperCase()}</th>}</tr></thead><tbody>
      {rows.map(([key, label]) => <tr key={key}><td>{label}</td><td>{latest.metrics[key] ?? 'Нет данных'}</td>
        <td className={latest.assessment[key] === 'warning' ? 'report-warning' : ''}>{({ ok: 'В пределах цели', warning: 'Вне цели', unavailable: 'Недоступно' })[latest.assessment[key]]}</td>
        {same && <td>{previous.metrics[key] ?? 'Нет данных'}</td>}</tr>)}
    </tbody></table></div>
    <p>DNS: {latest.dns_ms ?? '—'} мс. Общие TCP-повторы VPS за замер: {latest.host_tcp?.retrans_segments ?? '—'} (включая другие приложения).</p>
    {latest.warnings.length > 0 && <p className="report-warning">Часть проб недоступна. ICMP может фильтроваться; ошибка HTTPS или небольшой ответ не считаются измерением скорости.</p>}
  </>;
}

export function NetworkBenchmarkPanel({ nodeId, jobs, locked, onPreview }: {
  nodeId: string; jobs: Job[]; locked: boolean; onPreview: (profile: BenchmarkProfile) => void;
}) {
  const storageKey = 'nodekit-benchmark-' + nodeId;
  const [profile, setProfile] = useState<BenchmarkProfile>(() => {
    try { return { ...defaults, ...JSON.parse(localStorage.getItem(storageKey) || '{}') }; }
    catch { return defaults; }
  });
  const [reports, setReports] = useState<BenchmarkReport[]>([]);
  const [error, setError] = useState('');
  const ids = jobs.filter(j => j.action === 'network_benchmark' && j.status === 'succeeded')
    .sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 2).map(j => j.id).join(',');
  useEffect(() => {
    let active = true;
    setError('');
    Promise.all(ids.split(',').filter(Boolean).map(id => api<JobDetail>('/jobs/' + id)))
      .then(items => { if (active) setReports(items.flatMap(j => j.report?.network_benchmark ? [j.report.network_benchmark] : [])); })
      .catch(() => { if (active) setError('Не удалось загрузить историю замеров.'); });
    return () => { active = false; };
  }, [ids]);
  return <section className="card"><div className="section-heading"><div><h2>Измеряемый профиль сети</h2><p>Цели задаёт оператор. Сравнивай один маршрут и одинаковую нагрузку до/после BBR.</p></div></div>
    <div className="card-content"><form onSubmit={event => {
      event.preventDefault();
      try { localStorage.setItem(storageKey, JSON.stringify(profile)); } catch { /* Storage may be disabled. */ }
      onPreview(profile);
    }}>
      <label htmlFor="benchmark-url">HTTPS URL тестового файла (от 1 МиБ)</label>
      <input id="benchmark-url" type="url" required maxLength={400} placeholder="https://ваш-сервер/test.bin" value={profile.url}
        onChange={e => setProfile({ ...profile, url: e.target.value })} />
      <div className="form-grid">{fields.map(([name, label]) => <label key={name}>{label}<input type="number" required step="0.1" min={name.startsWith('min_') || name === 'max_rtt_ms' ? 0.1 : 0}
        max={name === 'max_loss_percent' ? 100 : 100000} value={profile[name]} onChange={e => setProfile({ ...profile, [name]: Number(e.target.value) })} /></label>)}</div>
      <Button type="submit" disabled={locked}>Подготовить замер</Button>
    </form>
    <p className="feature-hint">До 48 МиБ входящего трафика и 60 секунд HTTPS. Измеряется прямое скачивание на VPS; мобильный участок, UDP, upload и SSH-туннель требуют отдельных проб. Текущие SSH-туннели продолжат использовать прежний алгоритм до переподключения. Цели сохраняются в этом браузере и в отчёте задания.</p>
    {error && <p role="alert">{error}</p>}
    <BenchmarkComparison reports={reports} />
    </div></section>;
}
