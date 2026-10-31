import type { InstallationReport, PanelFinding, InboundFinding } from '../../types';
import { StatusBadge, Button } from '../../framework/components';

const labels: Record<string, string> = {
  upstream: 'HTTP-сервер подписок', caddy_upstream: 'Caddy → сервер подписок',
  port: 'Публичный HTTPS-порт', route: 'Маршрут в Caddyfile', https: 'DNS и HTTPS подписок с VPS',
  inbound_ports: 'Порты inbound и Caddy',
};
const states = { ok: 'Проверено', error: 'Ошибка', warning: 'Нужна проверка', not_checked: 'Не проверено' };

export function SubscriptionReport({ report }: { report: InstallationReport }) {
  const checks = report.subscription_checks || [];
  if (!checks.length) return null;
  return <div className="report-section">
    <h3>Подписки: проверка по участкам</h3>
    {report.subscription_url_template && <code className="subscription-template">{report.subscription_url_template}</code>}
    <div className="subscription-checks">
      {checks.map((check) => <div className="subscription-check" key={check.name}>
        <div><strong>{labels[check.name] || check.name}</strong>
          <StatusBadge tone={check.state === 'ok' ? 'mint' : check.state === 'error' ? 'red' : 'amber'}>{states[check.state]}</StatusBadge></div>
        <p>{check.detail}</p>
      </div>)}
    </div>
    <p className="feature-hint">HTTPS проверяется с VPS с проверкой сертификата. Доступ с телефона/компьютера и VPN-трафик проверяются отдельно. Токены и содержимое подписок в отчёт не попадают.</p>
  </div>;
}

export function InboundReport({ panel, busy = false, onEdit, onDelete, onTest }: { panel: PanelFinding; busy?: boolean;
  onEdit?: (item: InboundFinding) => void; onDelete?: (item: InboundFinding) => void; onTest?: (item: InboundFinding) => void }) {
  if (!panel.inbounds_readable) return <p className="feature-hint">Inbound не прочитаны. Повтори обнаружение после обновления Nodekit; существующие записи не изменяются.</p>;
  const inbounds = panel.inbounds || [];
  return <div className="report-section">
    <h3>Inbound и клиенты ({inbounds.length})</h3>
    {!inbounds.length ? <p className="feature-hint">Inbound пока нет. Их можно создать через параметры ноды и операцию «Подписки и inbound».</p> :
      <div className="table-scroll"><table className="data-table inbound-table">
        <thead><tr><th>Inbound</th><th>Протокол</th><th>Принимает</th><th>Состояние</th><th>Клиенты</th>{onEdit && <th>Действия</th>}</tr></thead>
        <tbody>{inbounds.map((item) => <tr key={item.id}>
          <td><strong>{item.remark || 'Inbound ' + item.id}</strong><small>#{item.id}</small></td>
          <td>{item.protocol.toUpperCase()}<small>{[item.network, item.security].filter(Boolean).join(' · ')}</small></td>
          <td><code>{item.listen}:{item.port}</code></td>
          <td><StatusBadge tone={item.enabled ? 'mint' : 'amber'}>{item.enabled ? 'Включён' : 'Выключен'}</StatusBadge></td>
          <td><strong>{item.client_count}</strong>{item.clients.map((client, i) => <small key={i}>
            {client.email || 'Без имени'} · {client.enabled ? 'включён' : 'выключен'} · {client.has_subscription ? 'ID подписки задан' : 'без ID подписки'}
          </small>)}</td>
          {onEdit && <td><div className="inbound-actions">
            <Button small disabled={busy || !item.fingerprint} onClick={() => onEdit(item)}>Изменить</Button>
            <Button small disabled={busy || !item.fingerprint || !item.enabled || item.protocol !== 'vless' || item.security !== 'reality' || !['tcp', 'raw'].includes(item.network)} onClick={() => onTest?.(item)}>Проверить трафик</Button>
            <Button small className="danger-button" disabled={busy || !item.fingerprint} onClick={() => onDelete?.(item)}>Удалить</Button>
          </div></td>}
        </tr>)}</tbody>
      </table></div>}
    {panel.inbounds_truncated && <p className="report-warning">Достигнут лимит отчёта: показана часть inbound/клиентов.</p>}
    <p className="feature-hint">Снимок из базы панели. UUID, пароли, ключи REALITY и ID подписок скрыты. Обнаружение не меняет inbound и клиентов.</p>
  </div>;
}
