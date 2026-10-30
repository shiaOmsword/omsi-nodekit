import { messages } from '../../framework/messages';
import type { NodeRecord, NodeState } from '../../types';

interface Props {
  selected: NodeRecord | null;
  busy: boolean;
  onState: (state: NodeState) => void;
  onDelete: () => void;
}

/** These actions change only local Nodekit metadata, never the remote VPS. */
export function NodeLifecycle({ selected, busy, onState, onDelete }: Props) {
  if (!selected) return null;
  return <div className="node-lifecycle">
    <span className="node-lifecycle-state">{messages.lifecycle.state}: {messages.lifecycle.status[selected.state]}</span>
    {selected.state === 'active' && <>
      <button type="button" disabled={busy} onClick={() => onState('hidden')}>{messages.lifecycle.hide}</button>
      <button type="button" disabled={busy} onClick={() => onState('archived')}>{messages.lifecycle.archive}</button>
    </>}
    {selected.state === 'hidden' && <>
      <button type="button" disabled={busy} onClick={() => onState('active')}>{messages.lifecycle.show}</button>
      <button type="button" disabled={busy} onClick={() => onState('archived')}>{messages.lifecycle.archive}</button>
    </>}
    {selected.state === 'archived' && <button type="button" disabled={busy} onClick={() => onState('active')}>{messages.lifecycle.unarchive}</button>}
    <button type="button" className="node-lifecycle-delete" disabled={busy} onClick={onDelete}>{messages.lifecycle.delete}</button>
  </div>;
}
