import type { ReactNode } from 'react';
export function StatusBadge({ tone = 'mint', children }: { tone?: 'mint' | 'amber'; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
