import { useState } from 'react';
import { messages } from '../messages';
import { Button } from './Button';

export function CodeBlock({ value, label }: { value: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  async function copy() {
    try { await navigator.clipboard.writeText(value); setState('copied'); }
    catch { setState('failed'); }
  }
  return <div className="code-block"><div><span>{label}</span><Button small onClick={copy}>
    {state === 'copied' ? messages.code.copied : messages.code.copy}
  </Button></div><pre aria-label={label} tabIndex={0}>{value}</pre>
    {state === 'failed' && <p role="status">{messages.code.failed}</p>}
  </div>;
}
