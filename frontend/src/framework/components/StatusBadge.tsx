import type { ReactNode } from 'react';
export function StatusBadge({ tone = 'mint', children }: { tone?: 'mint' | 'amber' | 'red'; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
