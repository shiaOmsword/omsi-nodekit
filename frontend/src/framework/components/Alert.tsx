import { Check, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { messages } from '../messages';

export function Alert({ tone, children, onClose }: { tone: 'error' | 'success'; children: ReactNode; onClose?: () => void }) {
  return <div className={`alert ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    {tone === 'success' && <Check size={16} aria-hidden="true" />}
    <span>{children}</span>
    {onClose && <button type="button" onClick={onClose} aria-label={messages.error.close}><X size={16} aria-hidden="true" /></button>}
  </div>;
}
