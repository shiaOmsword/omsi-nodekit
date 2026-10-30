import { Network, ShieldCheck } from 'lucide-react';
import { Alert, CardHeader, StatusBadge } from '../../framework/components';
import { formatMessage, messages } from '../../framework/messages';
import type { CertificateFinding, InstallationReport } from '../../types';

const t = messages.report;
const empty = (value: string | null | undefined) => value || t.empty;

function Warnings({ values }: { values: string[] }) {
  return <>{[...new Set(values)].map(value => <p className="report-warning" key={value}>{value}</p>)}</>;
}
function Certificate({ item }: { item: CertificateFinding }) {
  const state = Object.hasOwn(t.certificateStates, item.state)
    ? t.certificateStates[item.state as keyof typeof t.certificateStates] : t.unknown;
  return <div className="certificate-item"><div><strong>{item.usage === 'panel' ? t.panel : t.subscription}</strong>
    <StatusBadge tone={item.state === 'valid' ? 'mint' : 'amber'}>{state}</StatusBadge></div>
    {item.state !== 'not_configured' && <dl className="detail-list">
      <dt>{t.cert}</dt><dd>{empty(item.cert_path)}</dd><dt>{t.key}</dt><dd>{empty(item.key_path)}</dd>
      <dt>{t.expires}</dt><dd>{empty(item.not_after)}</dd><dt>{t.keyReadable}</dt><dd>{item.key_readable === null ? t.unknown : item.key_readable ? t.yes : t.no}</dd>
    </dl>}
  </div>;
}

export function InstallationReportView({ report, node }: { report: InstallationReport; node: string }) {
  return <section className="card inventory-card"><CardHeader icon={<Network size={18}/>} title={t.title}
    subtitle={formatMessage(t.subtitle, { node })} trailing={<time dateTime={report.observed_at}>{new Date(report.observed_at).toLocaleString('ru-RU')}</time>}/>
    <div className="inventory-content">
      <div className="capabilities"><span>{t.capabilities}</span>{Object.entries(report.capabilities).map(([name, available]) => <StatusBadge key={name} tone={available ? 'mint' : 'amber'}>{name} · {available ? t.yes : t.no}</StatusBadge>)}</div>
      {!!report.profiles?.length && <>
        <h2>{t.profiles}</h2><p className="feature-hint">{t.profilesHint}</p>
        <div className="table-scroll"><table><thead><tr>
          <th>{t.panelRuntime}</th><th>{t.caddyRuntime}</th><th>{t.missingTools}</th>
        </tr></thead><tbody>{report.profiles.map(profile => <tr key={`${profile.panel_runtime}-${profile.caddy_runtime}`}>
          <td>{profile.panel_runtime === 'native' ? t.runtimeNative : t.runtimeDocker}</td>
          <td>{profile.caddy_runtime === 'none' ? t.caddyNone : profile.caddy_runtime === 'native' ? t.runtimeNative : t.runtimeDocker}</td>
          <td><StatusBadge tone={profile.ready ? 'mint' : 'amber'}>{profile.ready ? t.toolsReady : profile.missing.join(', ')}</StatusBadge></td>
        </tr>)}</tbody></table></div>
      </>}
      <Warnings values={report.warnings}/>
      {!report.selected_panel && <Alert tone="error">{t.notSelected}</Alert>}
      <h2>{t.panels}</h2>{!report.panels.length && <p className="feature-hint">{t.noPanels}</p>}
      {report.panels.map(panel => <article className="finding" key={panel.id}>
        <div className="finding-heading"><strong>{panel.container || panel.service || panel.id}</strong><span>{panel.installation}</span>
          <StatusBadge tone={panel.active ? 'mint' : 'amber'}>{panel.active ? t.active : t.inactive}</StatusBadge>
          {report.selected_panel === panel.id && <StatusBadge tone="mint">{t.selected}</StatusBadge>}</div>
        <dl className="detail-list"><dt>{t.database}</dt><dd>{empty(panel.database_path)}</dd>
          {panel.network_mode && <><dt>{t.mode}</dt><dd>{panel.network_mode}</dd><dt>{t.network}</dt><dd>{panel.networks.join(', ') || t.empty}</dd>
            <dt>{t.ports}</dt><dd>{panel.published_ports.join(', ') || t.empty}</dd></>}</dl>
        <Warnings values={panel.warnings}/>
        {!!panel.defaulted_settings.length && <p className="feature-hint">{formatMessage(t.defaults, { fields: panel.defaulted_settings.join(', ') })}</p>}
        <details><summary>{t.settings}</summary><dl className="detail-list">{Object.entries(panel.settings).map(([key, value]) => <div className="detail-pair" key={key}><dt>{key}</dt><dd>{empty(value)}</dd></div>)}</dl></details>
        <h3><ShieldCheck size={15}/>{t.certificates}</h3>
        <div className="certificate-grid">{panel.certificates.map(cert => <Certificate item={cert} key={cert.usage}/>)}</div>
      </article>)}
      <p className="feature-hint">{t.metadataOnly}</p>
      <h2>{t.caddy}</h2>{!report.caddy.length && <p className="feature-hint">{t.noCaddy}</p>}
      {report.caddy.map(proxy => <article className="finding" key={proxy.id}>
        <div className="finding-heading"><strong>{proxy.container || proxy.service || proxy.id}</strong><span>{proxy.installation}</span>
          <StatusBadge tone={proxy.active ? 'mint' : 'amber'}>{proxy.active ? t.active : t.inactive}</StatusBadge></div>
        <dl className="detail-list"><dt>{t.config}</dt><dd>{empty(proxy.config_path)}</dd><dt>{t.mode}</dt><dd>{empty(proxy.network_mode)}</dd>
          <dt>{t.network}</dt><dd>{proxy.networks.join(', ') || t.empty}</dd><dt>{t.ports}</dt><dd>{proxy.published_ports.join(', ') || t.empty}</dd></dl>
        <Warnings values={proxy.warnings}/>
        {proxy.routes.length ? <div className="table-scroll"><table><thead><tr><th>{t.listen}</th><th>{t.hosts}</th><th>{t.paths}</th><th>{t.upstreams}</th></tr></thead>
          <tbody>{proxy.routes.map((route, index) => <tr key={index}><td>{route.listen.join(', ') || t.empty}</td><td>{route.hosts.join(', ') || t.empty}</td><td>{route.paths.join(', ') || t.empty}</td><td>{route.upstreams.join(', ') || t.empty}</td></tr>)}</tbody></table></div>
          : <p className="feature-hint">{t.noRoutes}</p>}
      </article>)}
    </div>
  </section>;
}
