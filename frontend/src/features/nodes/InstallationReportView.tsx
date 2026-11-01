import type { ReactNode } from 'react';
import { Box, CheckCircle2, CircleHelp, Server, ShieldCheck } from 'lucide-react';
import { Alert, StatusBadge } from '../../framework/components';
import { formatMessage, messages } from '../../framework/messages';
import type { CertificateFinding, InstallationReport } from '../../types';
import { formatDate } from '../../app/format';
import { InboundReport, SubscriptionReport } from './SubscriptionReport';
import { NetworkReport } from './NetworkReport';

const t = messages.report;
const empty = (value: string | null | undefined) => value || t.empty;
const capabilityNames: Record<string, string> = {
  docker: 'Docker CLI',
  docker_engine: 'Docker Engine',
  compose: 'Docker Compose',
  systemctl: 'systemd',
  openssl: 'OpenSSL',
  ssh: 'SSH',
  sudo: 'sudo',
  curl: 'curl',
  tar: 'tar',
  caddy: 'Caddy в системе',
  python3: 'Python 3.11+',
  root: 'Права root',
};
function Warnings({ values }: { values: string[] }) {
  return (
    <>
      {[...new Set(values)].map((value) => (
        <p className="report-warning" key={value}>
          {value}
        </p>
      ))}
    </>
  );
}
function Certificate({ item }: { item: CertificateFinding }) {
  const state = Object.hasOwn(t.certificateStates, item.state)
    ? t.certificateStates[item.state as keyof typeof t.certificateStates]
    : t.unknown;
  return (
    <div className="certificate-item">
      <div>
        <strong>{item.usage === 'panel' ? t.panel : t.subscription}</strong>
        <StatusBadge tone={item.state === 'valid' ? 'mint' : 'amber'}>{state}</StatusBadge>
      </div>
      {item.state !== 'not_configured' && (
        <dl className="detail-list">
          <dt>{t.cert}</dt>
          <dd>{empty(item.cert_path)}</dd>
          <dt>{t.key}</dt>
          <dd>{empty(item.key_path)}</dd>
          <dt>{t.expires}</dt>
          <dd>{empty(item.not_after)}</dd>
          <dt>{t.keyReadable}</dt>
          <dd>{item.key_readable === null ? t.unknown : item.key_readable ? t.yes : t.no}</dd>
        </dl>
      )}
    </div>
  );
}
export function InstallationReportView({
  report,
  node,
  suggestions,
  compact = false,
}: {
  report: InstallationReport;
  node: string;
  suggestions?: ReactNode;
  compact?: boolean;
}) {
  const activePanels = report.panels.filter((p) => p.active).length;
  const activeCaddy = report.caddy.filter((p) => p.active).length;
  return (
    <section className="card inventory-card">
      <div className="section-heading">
        <div>
          <h2>Состояние сервера</h2>
          <p>
            {node} · обнаружено {formatDate(report.observed_at)}
          </p>
        </div>
        <span className="muted">
          <CheckCircle2 size={18} />
          Снимок конфигурации
        </span>
      </div>
      <div className="inventory-content">
        <div className="report-summary">
          <div>
            <Server size={20} />
            <span>Панель 3x-ui</span>
            <strong>
              {!report.panels.length
                ? report.warnings.length
                  ? 'Не удалось определить'
                  : 'Не обнаружена'
                : activePanels
                  ? 'Работает'
                  : 'Остановлена'}
            </strong>
            <small>
              {!report.panels.length
                ? report.warnings.length
                  ? 'Данные прочитаны не полностью'
                  : 'Можно подготовить новую установку'
                : report.panels.length + ' обнаружено · ' + activePanels + ' запущено'}
            </small>
          </div>
          <div>
            <Box size={20} />
            <span>Caddy</span>
            <strong>
              {!report.caddy.length ? 'Не обнаружен' : activeCaddy ? 'Работает' : 'Остановлен'}
            </strong>
            <small>
              {!report.caddy.length
                ? 'Нужен только для выбранного HTTPS-сценария'
                : report.caddy.map((c) => c.container || c.service || c.installation).join(', ')}
            </small>
          </div>
          <div>
            <ShieldCheck size={20} />
            <span>Что проверено</span>
            <strong>Конфигурация</strong>
            <small>Доступность VPN-трафика проверяется отдельно</small>
          </div>
        </div>
        {!!report.panels.length && !report.selected_panel && (
          <Alert tone="error">{t.notSelected}</Alert>
        )}
        <Warnings values={report.warnings} />
        {suggestions}
        <SubscriptionReport report={report} />
        {!compact && <NetworkReport report={report} />}
        {!!report.panels.length && (
          <div className="report-section">
            <h3>Установки 3x-ui</h3>
            {report.panels.map((panel) => (
              <article className="finding" key={panel.id}>
                <div className="finding-heading">
                  <strong>{panel.container || panel.service || panel.id}</strong>
                  <span>
                    {panel.installation === 'native'
                      ? 'В системе'
                      : panel.container
                        ? 'Docker'
                        : 'Nodekit'}
                  </span>
                  <StatusBadge tone={panel.active ? 'mint' : 'amber'}>
                    {panel.active ? t.active : t.inactive}
                  </StatusBadge>
                  {report.selected_panel === panel.id && <StatusBadge>{t.selected}</StatusBadge>}
                </div>
                <dl className="detail-list">
                  <dt>{t.database}</dt>
                  <dd>{empty(panel.database_path)}</dd>
                  {panel.network_mode && (
                    <>
                      <dt>{t.mode}</dt>
                      <dd>{panel.network_mode}</dd>
                      <dt>{t.network}</dt>
                      <dd>{panel.networks.join(', ') || t.empty}</dd>
                      <dt>{t.ports}</dt>
                      <dd>{panel.published_ports.join(', ') || t.empty}</dd>
                    </>
                  )}
                </dl>
                <Warnings values={panel.warnings} />
                {!compact && <InboundReport panel={panel} />}
                <details className="report-details">
                  <summary>{t.settings}</summary>
                  {!!panel.defaulted_settings.length && (
                    <p className="feature-hint">
                      {formatMessage(t.defaults, { fields: panel.defaulted_settings.join(', ') })}
                    </p>
                  )}
                  <dl className="detail-list">
                    {Object.entries(panel.settings).map(([key, value]) => (
                      <div className="detail-pair" key={key}>
                        <dt>{key}</dt>
                        <dd>{empty(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
                <details className="report-details">
                  <summary>{t.certificates}</summary>
                  <div className="certificate-grid">
                    {panel.certificates.map((cert) => (
                      <Certificate item={cert} key={cert.usage} />
                    ))}
                  </div>
                  <p className="feature-hint">{t.metadataOnly}</p>
                  {!!report.subscription_checks?.length && <p className="feature-hint">
                    При HTTPS через Caddy встроенный TLS подписок в 3x-ui не требуется. Результат проверки HTTPS смотри в блоке подписок выше.
                  </p>}
                </details>
              </article>
            ))}
          </div>
        )}
        {!!report.caddy.length && (
          <div className="report-section">
            <h3>Caddy</h3>
            {report.caddy.map((proxy) => (
              <article className="finding" key={proxy.id}>
                <div className="finding-heading">
                  <strong>{proxy.container || proxy.service || proxy.id}</strong>
                  <span>{proxy.installation === 'docker' ? 'Docker' : 'В системе'}</span>
                  <StatusBadge tone={proxy.active ? 'mint' : 'amber'}>
                    {proxy.active ? t.active : t.inactive}
                  </StatusBadge>
                </div>
                <dl className="detail-list">
                  <dt>{t.config}</dt>
                  <dd>{empty(proxy.config_path)}</dd>
                  <dt>{t.mode}</dt>
                  <dd>{empty(proxy.network_mode)}</dd>
                  <dt>{t.network}</dt>
                  <dd>{proxy.networks.join(', ') || t.empty}</dd>
                  <dt>{t.ports}</dt>
                  <dd>{proxy.published_ports.join(', ') || t.empty}</dd>
                </dl>
                <Warnings values={proxy.warnings} />
                <details className="report-details">
                  <summary>Маршруты проксирования ({proxy.routes.length})</summary>
                  {proxy.routes.length ? (
                    <div className="table-scroll">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>{t.listen}</th>
                            <th>{t.hosts}</th>
                            <th>{t.paths}</th>
                            <th>{t.upstreams}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {proxy.routes.map((route, index) => (
                            <tr key={index}>
                              <td>{route.listen.join(', ') || t.empty}</td>
                              <td>{route.hosts.join(', ') || t.empty}</td>
                              <td>{route.paths.join(', ') || t.empty}</td>
                              <td>{route.upstreams.join(', ') || t.empty}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="feature-hint">{t.noRoutes}</p>
                  )}
                </details>
              </article>
            ))}
          </div>
        )}
        <details className="report-details">
          <summary>
            Системные инструменты ({Object.values(report.capabilities).filter(Boolean).length}{' '}
            доступны)
          </summary>
          <div className="capability-grid">
            {Object.entries(report.capabilities).map(([name, available]) => (
              <div key={name}>
                <span>{capabilityNames[name] || name}</span>
                <StatusBadge tone={available ? 'mint' : 'amber'}>
                  {available ? 'Доступен' : 'Не найден'}
                </StatusBadge>
              </div>
            ))}
          </div>
        </details>
        {!!report.profiles?.length && (
          <details className="report-details">
            <summary>Другие варианты размещения</summary>
            <p className="feature-hint">
              <CircleHelp size={16} />
              {t.profilesHint}
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>3x-ui</th>
                    <th>Caddy</th>
                    <th>Зависимости</th>
                  </tr>
                </thead>
                <tbody>
                  {report.profiles.map((profile) => (
                    <tr key={profile.panel_runtime + '-' + profile.caddy_runtime}>
                      <td>
                        {profile.panel_runtime === 'native' ? t.runtimeNative : t.runtimeDocker}
                      </td>
                      <td>
                        {profile.caddy_runtime === 'none'
                          ? t.caddyNone
                          : profile.caddy_runtime === 'native'
                            ? t.runtimeNative
                            : t.runtimeDocker}
                      </td>
                      <td>
                        <StatusBadge tone={profile.ready ? 'mint' : 'amber'}>
                          {profile.ready
                            ? 'Инструменты найдены'
                            : 'Нужны: ' + profile.missing.join(', ')}
                        </StatusBadge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
