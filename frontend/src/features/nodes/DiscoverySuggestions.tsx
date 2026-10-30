import { useEffect, useState } from 'react';
import { Button } from '../../framework/components';
import type { InstallationReport } from '../../types';
import { deploymentMessages as t } from './deploymentMessages';

export interface DiscoveryChoice { panel_id: string | null; caddy_id: string | null; role: 'ingress' | 'exit' }

export function DiscoverySuggestions({ report, disabled, onApply }: {
  report: InstallationReport; disabled: boolean; onApply: (choice: DiscoveryChoice) => void;
}) {
  const panelDefault = report.selected_panel || (report.panels.length === 1 ? report.panels[0].id : '');
  const [panel, setPanel] = useState(panelDefault);
  const [caddy, setCaddy] = useState('');
  const [role, setRole] = useState<'ingress' | 'exit'>('exit');
  useEffect(() => { setPanel(panelDefault); setCaddy(''); }, [report.observed_at, panelDefault]);
  return <div className="discovery-suggestions"><h3>{t.discovery}</h3><p className="feature-hint">{t.discoveryHint}</p>
    <div className="connection-fields">
      {!!report.panels.length && <label className="form-field"><span>{t.panelChoice}</span><select value={panel} disabled={disabled} onChange={e => setPanel(e.target.value)}>
        <option value="">{t.choosePanel}</option>{report.panels.map(p => <option key={p.id} value={p.id}>{p.container || p.service || p.id} · {p.installation}</option>)}</select></label>}
      {!report.panels.length && <>
        <label className="form-field"><span>{t.role}</span><select value={role} disabled={disabled} onChange={e => setRole(e.target.value as 'ingress' | 'exit')}><option value="exit">{t.exit}</option><option value="ingress">{t.ingress}</option></select></label>
        <label className="form-field"><span>{t.caddyChoice}</span><select value={caddy} disabled={disabled} onChange={e => setCaddy(e.target.value)}><option value="">{t.noCaddy}</option>{report.caddy.map(c => <option key={c.id} value={c.id}>{c.container || c.service || c.id}</option>)}</select></label>
      </>}
    </div>
    <Button disabled={disabled || (!!report.panels.length && !panel)} onClick={() => onApply({ panel_id: panel || null, caddy_id: caddy || null, role })}>{t.apply}</Button>
  </div>;
}
