import type { InstallationReport } from '../../types';
import { StatusBadge } from '../../framework/components';

export function NetworkReport({ report }: { report: InstallationReport }) {
  const firewall = report.firewall;
  const checks = report.network_checks || [];
  const traffic = report.traffic_checks || [];
  const egress = report.egress;
  return <div className="network-report">
    <section className="report-section">
      <h3>Firewall и публикация портов</h3>
      <p>UFW: <StatusBadge tone={firewall?.state === 'active' ? 'mint' : 'amber'}>
        {({ active: 'Активен', inactive: 'Неактивен', unavailable: 'Не установлен', unknown: 'Не удалось прочитать' } as Record<string, string>)[firewall?.state || 'unknown']}
      </StatusBadge></p>
      {firewall?.default_incoming && <p className="feature-hint">Политики: входящие — {firewall.default_incoming}, исходящие — {firewall.default_outgoing}, маршрутизируемые — {firewall.default_routed}.</p>}
      <div className="subscription-checks">{checks.map((check, index) => <div className="subscription-check" key={index}>
        <div><strong>{({ ufw: 'Правило UFW', caddy_port: 'Публикация Caddy', direct_https: 'Выход с VPS', subscription_config: 'Настройки подписок', inbound_config: 'Настройки inbound' } as Record<string, string>)[check.name] || check.name}</strong>
          <StatusBadge tone={check.state === 'ok' ? 'mint' : check.state === 'error' ? 'red' : 'amber'}>{check.state === 'ok' ? 'Проверено' : check.state === 'error' ? 'Ошибка' : 'Проверить'}</StatusBadge></div>
        <p>{check.detail}</p></div>)}</div>
      <p className="feature-hint">Наличие правила не доказывает внешний доступ. Публикации Docker проверяются отдельно; UFW не включается и не сбрасывается автоматически.</p>
      {!!firewall?.rules.length && <details className="report-details"><summary>Правила UFW ({firewall.rules.length})</summary>
        <div className="table-scroll"><table className="data-table inbound-table"><thead><tr><th>№</th><th>Порт</th><th>Действие</th><th>Источник</th><th>Назначение</th><th>Интерфейс</th><th>Владелец</th></tr></thead>
          <tbody>{firewall.rules.map((rule) => <tr key={rule.number}><td>{rule.number}</td><td>{rule.port}/{rule.protocol}{rule.ipv6 && ' · IPv6'}</td><td>{rule.action} {rule.direction}</td>
            <td>{rule.source}</td><td>{rule.destination}</td><td>{rule.interface || 'Все'}</td><td>{rule.managed ? 'Nodekit' : 'Ручное / другое'}</td></tr>)}</tbody></table></div></details>}
      {firewall?.warnings.map((warning) => <p className="report-warning" key={warning}>{warning}</p>)}
      {report.caddy.filter((p) => p.compose_project).map((proxy) => <dl className="detail-list" key={proxy.id}>
        <dt>Caddy Compose</dt><dd>{proxy.compose_project} / {proxy.compose_service}</dd><dt>Исходные файлы</dt><dd>{proxy.compose_files?.join(', ')}</dd></dl>)}
    </section>
    <section className="report-section"><h3>Выходы и маршруты Xray</h3>
      {!egress?.readable ? <p className="feature-hint">Конфигурация Xray не прочитана. Повтори обнаружение активной панели Nodekit.</p> : <>
        <p className="feature-hint">Прямой выход имеет протокол freedom. Название outbound само по себе не определяет его назначение. Первый outbound по умолчанию: {egress.default_tag || 'не задан'}.</p>
        <div className="table-scroll"><table className="data-table"><thead><tr><th>Outbound</th><th>Протокол</th><th>Через другой outbound</th></tr></thead>
          <tbody>{egress.outbounds.map((outbound, index) => <tr key={index}><td>{outbound.tag || 'Без тега'}</td><td><StatusBadge tone={outbound.protocol === 'freedom' ? 'mint' : 'amber'}>{outbound.protocol}</StatusBadge></td><td>{outbound.via || '—'}</td></tr>)}</tbody></table></div>
        {!!egress.rules.length && <details className="report-details"><summary>Правила маршрутизации ({egress.rules.length})</summary>
          <div className="table-scroll"><table className="data-table inbound-table"><thead><tr><th>Порядок</th><th>Inbound tag</th><th>Outbound / balancer</th><th>Дополнительные условия</th></tr></thead>
            <tbody>{egress.rules.map((rule) => <tr key={rule.index}><td>{rule.index + 1}</td><td>{rule.inbound_tags.join(', ') || 'Любой'}</td><td>{rule.outbound_tag || rule.balancer_tag || '—'}</td><td>{rule.conditional ? 'Есть' : 'Нет'}</td></tr>)}</tbody></table></div></details>}
        {egress.warnings.map((warning) => <p className="report-warning" key={warning}>{warning}</p>)}
      </>}
    </section>
    {!!traffic.length && <section className="report-section"><h3>Проверка реального трафика</h3><div className="subscription-checks">
      {traffic.map((check, index) => <div className="subscription-check" key={index}><div><strong>{check.name === 'inbound' ? 'Через VLESS/REALITY' : check.name === 'direct' ? 'Напрямую с VPS' : 'Область проверки'}</strong>
        <StatusBadge tone={check.state === 'ok' ? 'mint' : check.state === 'error' ? 'red' : 'amber'}>{check.state === 'ok' ? 'Ответ получен' : check.state === 'error' ? 'Ошибка' : 'Информация'}</StatusBadge></div><p>{check.detail}</p></div>)}
    </div></section>}
  </div>;
}
