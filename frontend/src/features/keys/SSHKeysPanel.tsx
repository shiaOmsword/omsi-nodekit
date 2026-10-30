import { KeyRound, Plus, Trash2 } from 'lucide-react';
import { Button, CodeBlock, EmptyState, PageHeading } from '../../framework/components';
import { messages } from '../../framework/messages';
import type { SSHKey } from '../../types';
import { formatDate } from '../../app/format';

interface Props {
  keys: SSHKey[];
  onCreate: () => void;
  onDelete: (key: SSHKey) => void;
  onUse: (id: string) => void;
  onHelp: () => void;
}
export function SSHKeysPanel({ keys, onCreate, onDelete, onUse, onHelp }: Props) {
  return (
    <>
      <PageHeading
        title="SSH-ключи"
        description="Ключи доступа к серверам и их публичные части."
        actions={
          <>
            <Button onClick={onHelp}>Как подключить сервер</Button>
            <Button variant="primary" onClick={onCreate} icon={<Plus size={18} />}>
              Создать ключ
            </Button>
          </>
        }
      />
      {!keys.length ? (
        <section className="card">
          <EmptyState
            title="Пока нет SSH-ключей"
            description="Создай ключ и добавь его публичную часть в authorized_keys на сервере. Можно также использовать существующий файл ключа в настройках ноды."
            action={
              <Button onClick={onCreate} variant="primary">
                Создать ключ
              </Button>
            }
          />
        </section>
      ) : (
        <div className="keys-grid">
          {keys.map((key) => (
            <section className="card key-card" key={key.id}>
              <div className="key-card-heading">
                <span className="node-symbol">
                  <KeyRound size={22} />
                </span>
                <div>
                  <h2>{key.name}</h2>
                  <span className="muted">Создан {formatDate(key.created_at)}</span>
                </div>
                <span className="tag">Ed25519</span>
              </div>
              <p className="key-fingerprint mono">{key.fingerprint}</p>
              <CodeBlock value={key.public_key} label="Публичный ключ" />
              <div className="key-actions">
                <Button onClick={() => onUse(key.id)}>Назначить ноде</Button>
                <Button variant="text" icon={<Trash2 size={17} />} onClick={() => onDelete(key)}>
                  Удалить ключ
                </Button>
              </div>
            </section>
          ))}
        </div>
      )}
      <details className="card storage-note">
        <summary>Хранение и доступ к ключам</summary>
        <p>{messages.keys.storage}</p>
        <p>{messages.keys.passphrase}</p>
      </details>
    </>
  );
}
