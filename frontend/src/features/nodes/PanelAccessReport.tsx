import type { InstallationReport, NodeRecord } from '../../types';
import { readConfig } from '../../app/config';
import { Button, CodeBlock } from '../../framework/components';

export function PanelAccessReport({ record, report, locked, onSettings }: {
  record: NodeRecord; report: InstallationReport | null | undefined; locked: boolean; onSettings: () => void;
}) {
  const config = readConfig(record.yaml);
  const access = report?.panel_access;
  const panel = report?.panels.find(p => p.id === report.selected_panel);
  const port = Number(panel?.settings?.webPort || config.panel?.port || 2053);
  const backend = access?.backend_host || '127.0.0.1';
  const host = backend.includes(':') ? '[' + backend + ']' : backend;
  const command = `ssh -N -L 127.0.0.1:${port}:${host}:${port} -p ${config.ssh.port || 22} ${config.ssh.user || 'root'}@${config.ssh.host}`;
  const httpsPort = config.caddy?.https_port || 2096;
  const publicURL = `https://${config.caddy?.domain}${httpsPort === 443 ? '' : ':' + httpsPort}${config.panel?.base_path || '/nodekit/'}`;
  const ready = access?.configured && access.mode !== 'disabled' && access.public_url === publicURL;
  return <section className="card"><div className="section-heading"><div><h2>Доступ к 3x-ui</h2>
    <p>{access?.mode === 'basic_auth' ? 'Дополнительный логин и пароль Caddy' : access?.mode === 'ip_allowlist' ? 'Доступ по списку IP' : 'Публичный вход через Caddy не настроен'}</p></div>
    <div className="row-actions"><Button disabled={locked || !report || !panel?.active || panel.installation !== 'managed' || (config.panel?.installation || 'managed') !== 'managed'} onClick={onSettings}>Настроить доступ</Button>
      <Button disabled={!ready} onClick={() => window.open(publicURL, '_blank', 'noopener,noreferrer')}>Открыть 3x-ui</Button></div></div>
    <div className="card-content">{access?.public_url && <p><code>{access.public_url}</code></p>}
      {!access?.configured && <p className="feature-hint">Нужны актуальное обнаружение и применение сохранённых настроек. Статус здесь не заменяет внешнюю проверку HTTPS и ограничения доступа.</p>}
      <details><summary>Резервный SSH-вход</summary><CodeBlock label="SSH-туннель к приватной панели" value={command} />
        <p>После подключения: <code>http://127.0.0.1:{port}{config.panel?.base_path || '/nodekit/'}</code>. Используй свой SSH-ключ или профиль; при необходимости выбери другой свободный локальный порт. Для Docker Caddy адресом назначения может быть приватный gateway.</p>
      </details>
    </div></section>;
}
