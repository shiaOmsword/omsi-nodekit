import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { Button, IconButton } from './Button';
import { Alert } from './Alert';

export function Modal({
  title,
  description,
  children,
  footer,
  onClose,
  busy = false,
  wide = false,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    if (dialog && !dialog.open) dialog.showModal();
    return () => {
      dialog?.close();
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={'modal' + (wide ? ' modal-wide' : '')}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      aria-modal="true"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) closeRef.current();
      }}
      onClick={(event) => {
        if (busy || event.target !== event.currentTarget) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom
        )
          closeRef.current();
      }}
    >
      <header className="modal-heading">
        <div>
          <h2 id={titleId}>{title}</h2>
          {description && <p id={descriptionId}>{description}</p>}
        </div>
        <IconButton label="Закрыть окно" onClick={onClose} disabled={busy}>
          <X size={20} />
        </IconButton>
      </header>
      <div className="modal-body">{children}</div>
      {footer && <footer className="modal-footer">{footer}</footer>}
    </dialog>
  );
}

export interface FormField {
  name: string;
  label: string;
  type?: 'text' | 'password' | 'number' | 'select' | 'checkbox' | 'textarea';
  hint?: string;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
  min?: number;
  max?: number;
  maxLength?: number;
  pattern?: string;
  options?: { value: string; label: string }[];
}
export type FormValues = Record<string, string | boolean>;

export function FormFields({
  fields,
  values,
  onChange,
}: {
  fields: FormField[];
  values: FormValues;
  onChange: (name: string, value: string | boolean) => void;
}) {
  const prefix = useId();
  return (
    <div className="form-grid">
      {fields.map((field) => {
        const id = prefix + '-' + field.name;
        const hint = field.hint ? id + '-hint' : undefined;
        const common = {
          id,
          name: field.name,
          'aria-label': field.label,
          required: field.required,
          disabled: field.disabled,
          'aria-describedby': hint,
        };
        return (
          <div
            className={'form-field' + (field.type === 'checkbox' ? ' field-toggle' : '')}
            key={field.name}
          >
            {field.type !== 'checkbox' && (
              <label htmlFor={id}>
                {field.label}
                {field.required && <span aria-hidden="true"> *</span>}
              </label>
            )}
            {field.type === 'select' ? (
              <select
                {...common}
                value={String(values[field.name] ?? '')}
                onChange={(e) => onChange(field.name, e.target.value)}
              >
                {field.options?.map((option) => (
                  <option value={option.value} key={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : field.type === 'checkbox' ? (
              <label htmlFor={id}>
                <input
                  {...common}
                  type="checkbox"
                  checked={!!values[field.name]}
                  onChange={(e) => onChange(field.name, e.target.checked)}
                />
                {field.label}
              </label>
            ) : field.type === 'textarea' ? (
              <textarea
                {...common}
                rows={5}
                value={String(values[field.name] ?? '')}
                placeholder={field.placeholder}
                onChange={(e) => onChange(field.name, e.target.value)}
              />
            ) : (
              <input
                {...common}
                type={field.type || 'text'}
                value={String(values[field.name] ?? '')}
                placeholder={field.placeholder}
                min={field.min}
                max={field.max}
                maxLength={field.maxLength}
                pattern={field.pattern}
                autoComplete={field.type === 'password' ? 'new-password' : 'off'}
                onChange={(e) => onChange(field.name, e.target.value)}
              />
            )}
            {field.hint && <small id={hint}>{field.hint}</small>}
          </div>
        );
      })}
    </div>
  );
}

export function FormDialog({
  title,
  description,
  fields,
  values,
  onChange,
  onSubmit,
  onClose,
  busy,
  error,
  submit = 'Сохранить',
  children,
}: {
  title: string;
  description?: string;
  fields: FormField[];
  values: FormValues;
  onChange: (name: string, value: string | boolean) => void;
  onSubmit: () => void;
  onClose: () => void;
  busy: boolean;
  error?: string;
  submit?: string;
  children?: ReactNode;
}) {
  const id = useId();
  return (
    <Modal
      title={title}
      description={description}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button type="submit" form={id} variant="primary" loading={busy}>
            {submit}
          </Button>
        </>
      }
    >
      <form
        id={id}
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) onSubmit();
        }}
      >
        {error && <Alert tone="error">{error}</Alert>}
        <fieldset disabled={busy}>
          <FormFields fields={fields} values={values} onChange={onChange} />
          {children}
        </fieldset>
      </form>
    </Modal>
  );
}
