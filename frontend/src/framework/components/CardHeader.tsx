import type { ReactNode } from 'react';
export function CardHeader({ title, subtitle, icon, trailing }: { title: string; subtitle?: string; icon?: ReactNode; trailing?: ReactNode }) {
  return <div className="card-heading"><div>{icon && <span className="section-icon" aria-hidden="true">{icon}</span>}
    <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div></div>{trailing}</div>;
}
