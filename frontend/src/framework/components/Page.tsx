import type { ReactNode } from 'react';
import { FolderOpen, Search } from 'lucide-react';
import { Spinner } from './Spinner';

export function PageHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <FolderOpen size={24} />
      </span>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function Loading({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <Spinner size={22} />
      {label}
    </div>
  );
}
export function SearchInput({
  value,
  onChange,
  placeholder = 'Поиск',
  label = 'Поиск',
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
}) {
  return (
    <label className="search-field">
      <Search size={17} />
      <span className="sr-only">{label}</span>
      <input
        type="search"
        aria-label={label}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
