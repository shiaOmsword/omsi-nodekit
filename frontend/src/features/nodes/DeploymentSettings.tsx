import { useEffect, useState } from 'react';
import { Button } from '../../framework/components';
import type { DeploymentTarget, DraftConfig, InstallationReport } from '../../types';
import { deploymentMessages as t } from './deploymentMessages';

export const defaultTarget = (): DeploymentTarget => ({
  role: 'exit', panel_runtime: 'native', caddy_mode: 'none', caddy_id: null,
  subscription_bind: '127.0.0.1', install_docker: false, inbounds: [],
});

export function DeploymentSettings({ draft, report, busy, onApply }: {
  draft: DraftConfig | null; report: InstallationReport | null; busy: boolean;
  onApply: (target: DeploymentTarget) => void;
}) {
  const [target, setTarget] = useState<DeploymentTarget>(draft?.deployment || defaultTarget());
  useEffect(() => { setTarget(draft?.deployment || defaultTarget()); }, [draft]);
  const update = (changes: Partial<DeploymentTarget>) => setTarget(current => ({ ...current, ...changes }));
  const existing = report?.caddy || [];
  function selectCaddy(id: string) {
    const found = existing.find(item => item.id === id);
    update({ caddy_id: id || null, subscription_bind: found?.installation === 'docker' && found.network_mode !== 'host' ? found.host_gateway || '' : '127.0.0.1' });
  }
  return <details className="deployment-settings"><summary>{t.title}</summary>
    <p className="feature-hint">{t.hint}</p>
    <form onSubmit={event => { event.preventDefault(); onApply(target); }}>
      <fieldset disabled={busy || !draft}><div className="connection-fields">
        <label className="form-field"><span>{t.role}</span><select value={target.role} onChange={e => update({ role: e.target.value as DeploymentTarget['role'], panel_runtime: e.target.value === 'exit' ? 'native' : 'docker' })}>
          <option value="exit">{t.exit}</option><option value="ingress">{t.ingress}</option></select></label>
        <label className="form-field"><span>{t.panel}</span><select value={target.panel_runtime} onChange={e => update({ panel_runtime: e.target.value as DeploymentTarget['panel_runtime'] })}>
          <option value="native">{t.native}</option><option value="docker">{t.docker}</option></select></label>
        <label className="form-field"><span>{t.caddy}</span><select value={target.caddy_mode} onChange={e => update({ caddy_mode: e.target.value as DeploymentTarget['caddy_mode'], caddy_id: null, subscription_bind: '127.0.0.1' })}>
          <option value="none">{t.none}</option><option value="docker">{t.own}</option><option value="existing">{t.existing}</option></select></label>
        {target.caddy_mode === 'existing' && <label className="form-field"><span>{t.caddyChoice}</span><select required value={target.caddy_id || ''} onChange={e => selectCaddy(e.target.value)}>
          <option value="">—</option>{target.caddy_id && !existing.some(c => c.id === target.caddy_id) && <option value={target.caddy_id}>{target.caddy_id}</option>}
          {existing.map(c => <option key={c.id} value={c.id}>{c.container || c.service} · {c.installation}</option>)}</select></label>}
      </div>
      {target.caddy_mode !== 'none' && <p className="feature-hint">{t.caddyHint}</p>}
      {(target.panel_runtime === 'docker' || target.caddy_mode === 'docker') && <label className="deployment-check"><input type="checkbox" checked={target.install_docker} onChange={e => update({ install_docker: e.target.checked })}/>{t.installDocker}</label>}
      <h3>{t.inbounds}</h3><p className="feature-hint">{t.inboundHint}</p>
      {target.inbounds.map((inbound, index) => <div className="inbound-editor" key={index}>
        <label className="form-field"><span>{t.name}</span><input required pattern="[a-z][a-z0-9-]{0,31}" value={inbound.name} onChange={e => update({ inbounds: target.inbounds.map((v, i) => i === index ? { ...v, name: e.target.value } : v) })}/></label>
        <label className="form-field"><span>{t.port}</span><input type="number" required min="1" max="65535" value={inbound.port} onChange={e => update({ inbounds: target.inbounds.map((v, i) => i === index ? { ...v, port: Number(e.target.value) } : v) })}/></label>
        <label className="form-field"><span>{t.sni}</span><input required placeholder="www.example.com" value={inbound.server_name} onChange={e => update({ inbounds: target.inbounds.map((v, i) => i === index ? { ...v, server_name: e.target.value } : v) })}/></label>
        <label className="form-field"><span>{t.listen}</span><select value={inbound.listen} onChange={e => update({ inbounds: target.inbounds.map((v, i) => i === index ? { ...v, listen: e.target.value as '127.0.0.1' | '0.0.0.0' } : v) })}><option value="127.0.0.1">{t.local}</option><option value="0.0.0.0">{t.public}</option></select></label>
        <Button variant="text" onClick={() => update({ inbounds: target.inbounds.filter((_, i) => i !== index) })}>{t.remove}</Button>
      </div>)}
      <div className="connection-links"><Button variant="text" disabled={target.inbounds.length >= 12} onClick={() => update({ inbounds: [...target.inbounds, { name: `tunnel-${target.inbounds.length + 1}`, port: target.inbounds.length ? 8443 + target.inbounds.length - 1 : 443, listen: '127.0.0.1', server_name: '', target_port: 443 }] })}>{t.addInbound}</Button>
        <Button type="submit">{t.apply}</Button></div>
      </fieldset>
    </form>
  </details>;
}
