import { messages } from '../../framework/messages';
import { Button } from '../../framework/components';
import type { DraftConfig, Installation, SSHKey } from '../../types';

interface Props {
  draft: DraftConfig | null; keys: SSHKey[]; busy: boolean;
  onKey: (id: string) => void; onInstallation: (mode: Installation) => void;
  onManage: () => void; onHelp: () => void;
}

export function ConnectionSettings({ draft, keys, busy, onKey, onInstallation, onManage, onHelp }: Props) {
  const key = draft?.ssh.key_id || '';
  const missing = !!key && !keys.some(item => item.id === key);
  return <div className="connection-settings"><div className="connection-fields">
    <label className="form-field"><span>{messages.connection.installation}</span><select
      value={draft?.panel.installation || 'managed'} disabled={busy || !draft}
      onChange={event => onInstallation(event.target.value as Installation)}>
      {(['managed', 'auto', 'native', 'docker'] as const).map(mode => <option value={mode} key={mode}>{messages.connection[mode]}</option>)}
    </select></label>
    <label className="form-field"><span>{messages.connection.key}</span><select value={key} disabled={busy || !draft} onChange={e => onKey(e.target.value)}>
      <option value="">{messages.connection.externalKey}</option>
      {missing && <option value={key}>{messages.connection.missingKey}</option>}
      {keys.map(item => <option key={item.id} value={item.id}>{item.name} · {item.fingerprint.slice(0, 20)}…</option>)}
    </select></label>
  </div><div className="connection-links"><Button variant="text" onClick={onManage}>{messages.connection.manageKeys}</Button>
    <Button variant="text" onClick={onHelp}>{messages.connection.help}</Button></div>
    <p className="feature-hint">{!draft ? messages.connection.invalidYaml : draft.panel.installation === 'managed' ? messages.connection.rewritten : messages.connection.readOnly}</p>
  </div>;
}
