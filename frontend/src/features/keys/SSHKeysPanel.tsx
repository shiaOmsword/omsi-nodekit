import { useState } from 'react';
import { KeyRound, Trash2 } from 'lucide-react';
import { api, getErrorMessage } from '../../framework/api';
import { Alert, Button, CardHeader, CodeBlock } from '../../framework/components';
import { formatMessage, messages } from '../../framework/messages';
import type { SSHKey } from '../../types';

interface Props { keys: SSHKey[]; refresh: () => Promise<void>; onUse: (id: string) => void; onHelp: () => void }

export function SSHKeysPanel({ keys, refresh, onUse, onHelp }: Props) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await api<SSHKey>('/ssh-keys', { method: 'POST', body: JSON.stringify({ name }) });
      setName(''); await refresh(); setNotice(messages.keys.createdNotice);
    } catch (err) { setError(getErrorMessage(err)); }
    finally { setBusy(false); }
  }
  async function remove(key: SSHKey) {
    if (!window.confirm(formatMessage(messages.keys.deleteConfirm, { name: key.name }))) return;
    setBusy(true); setError(''); setNotice('');
    try { await api(`/ssh-keys/${key.id}`, { method: 'DELETE' }); await refresh(); setNotice(messages.keys.deletedNotice); }
    catch (err) { setError(getErrorMessage(err)); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><div className="eyebrow">OMSI NODEKIT</div><h1>{messages.keys.title}</h1><p>{messages.keys.subtitle}</p></div>
      <Button onClick={onHelp}>{messages.keys.manual}</Button></div>
    {error && <Alert tone="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert tone="success">{notice}</Alert>}
    <section className="card key-create"><CardHeader icon={<KeyRound size={18}/>} title={messages.keys.create}/>
      <form onSubmit={create}><label className="form-field"><span>{messages.keys.name}</span>
        <input required maxLength={80} value={name} onChange={e => setName(e.target.value)} placeholder={messages.keys.namePlaceholder} disabled={busy}/></label>
        <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>{messages.keys.generate}</Button></form>
      <p className="feature-hint">{messages.keys.storage}</p><p className="feature-hint">{messages.keys.passphrase}</p>
    </section>
    {!keys.length && <div className="feature-empty"><KeyRound size={28}/><h2>{messages.keys.empty}</h2><p>{messages.keys.emptyBody}</p></div>}
    <div className="keys-grid">{keys.map(key => <section className="card key-card" key={key.id}>
      <CardHeader icon={<KeyRound size={18}/>} title={key.name} subtitle={key.fingerprint}/>
      <CodeBlock value={key.public_key} label={messages.keys.publicKey}/>
      <div className="key-actions"><Button small onClick={() => onUse(key.id)} disabled={busy}>{messages.keys.use}</Button>
        <Button small variant="text" icon={<Trash2 size={14}/>} onClick={() => remove(key)} disabled={busy}>{messages.keys.delete}</Button></div>
    </section>)}</div>
  </>;
}
