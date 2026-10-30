import { Archive, Eye, Trash2 } from 'lucide-react';
import type { NodeState, NodeSummary } from '../../types';
import { Alert, Button, Modal } from '../../framework/components';

export function NodeManagementModal({
  node,
  busy,
  error,
  onClose,
  onState,
  onDelete,
}: {
  node: NodeSummary;
  busy: boolean;
  error: string;
  onClose: () => void;
  onState: (state: NodeState) => void;
  onDelete: () => void;
}) {
  return (
    <Modal title="Управление нодой" description={node.name} onClose={onClose} busy={busy}>
      <div className="management-actions">
        {error && <Alert tone="error">{error}</Alert>}
        {node.state !== 'active' && (
          <Button icon={<Eye size={18} />} disabled={busy} onClick={() => onState('active')}>
            {node.state === 'archived' ? 'Вернуть из архива' : 'Показать ноду'}
          </Button>
        )}
        {node.state === 'active' && (
          <Button icon={<Eye size={18} />} disabled={busy} onClick={() => onState('hidden')}>
            Скрыть из активного списка
          </Button>
        )}
        {node.state !== 'archived' && (
          <Button icon={<Archive size={18} />} disabled={busy} onClick={() => onState('archived')}>
            Переместить в архив
          </Button>
        )}
        <Button
          variant="text"
          className="danger-text"
          icon={<Trash2 size={18} />}
          disabled={busy}
          onClick={onDelete}
        >
          Удалить из Nodekit
        </Button>
        <p className="feature-hint">
          Эти действия меняют запись в локальной панели. Сервисы на VPS продолжают работать.
        </p>
      </div>
    </Modal>
  );
}
