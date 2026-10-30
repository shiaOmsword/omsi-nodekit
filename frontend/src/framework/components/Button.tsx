import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { Spinner } from './Spinner';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'text';
  small?: boolean;
  full?: boolean;
  loading?: boolean;
  icon?: ReactNode;
}
export function Button({ variant = 'secondary', small, full, loading, icon, children,
  className = '', disabled, type = 'button', ...props }: ButtonProps) {
  const base = variant === 'text' ? 'text-button' : `button ${variant}`;
  return <button {...props} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
    className={[base, small && 'small', full && 'full', className].filter(Boolean).join(' ')}>
    {loading ? <Spinner /> : icon}{children}
  </button>;
}
export function IconButton({ label, children, className = '', type = 'button', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button {...props} type={type} aria-label={label} title={props.title ?? label}
    className={`icon-button ${className}`.trim()}>{children}</button>;
}
