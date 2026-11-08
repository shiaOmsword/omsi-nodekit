import { useState } from 'react';
import { Download, FileArchive, RotateCcw, Upload } from 'lucide-react';
import type { Backup } from '../../types';
import { Button, EmptyState, PageHeading, SearchInput } from '../../framework/components';
import { formatBytes, formatDate } from '../../app/format';

export function BackupsPage({
  backups,
  onImport,
  onRestore,
  onClients,
}: {
  backups: Backup[];
  onImport: () => void;
  onRestore: (backup: Backup) => void;
  onClients: (backup: Backup) => void;
}) {
  const [search, setSearch] = useState('');
  const visible = backups.filter((b) =>
    (b.filename + ' ' + b.sha256).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <PageHeading
        title="Бэкапы"
        description="Снимки 3x-ui и wg-easy v15. Перенос wg-easy доступен в Inbound → + WireGuard на новой ноде."
        actions={
          <Button variant="primary" onClick={onImport} icon={<Upload size={18} />}>
            Загрузить бэкап
          </Button>
        }
      />
      <div className="toolbar">
        <span className="muted">
          {backups.length} файлов · {formatBytes(backups.reduce((sum, b) => sum + b.size, 0))}
        </span>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Имя файла или SHA256"
          label="Поиск бэкапов"
        />
      </div>
      <section className="card">
        {!visible.length ? (
          <EmptyState
            title={backups.length ? 'Ничего не найдено' : 'Бэкапов пока нет'}
            description="Создай бэкап на странице ноды или загрузи существующий файл SQLite."
            action={!backups.length && <Button onClick={onImport}>Загрузить .db</Button>}
          />
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Файл</th>
                  <th>Создан</th>
                  <th>Размер</th>
                  <th>SHA256</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((backup) => (
                  <tr key={backup.id}>
                    <td>
                      <span className="file-name">
                        <FileArchive size={19} />
                        {backup.filename}
                      </span>
                    </td>
                    <td className="nowrap">{formatDate(backup.created_at)}</td>
                    <td className="nowrap">{formatBytes(backup.size)}</td>
                    <td>
                      <span className="mono fingerprint" title={backup.sha256}>
                        {backup.sha256.slice(0, 14)}…
                      </span>
                    </td>
                    <td>
                      <div className="row-actions">
                        <a
                          className="button secondary small"
                          href={'/api/backups/' + backup.id + '/download'}
                        >
                          <Download size={16} />
                          Скачать
                        </a>
                        <Button small onClick={() => onClients(backup)}>Клиенты</Button>
                        <button
                          className="icon-button"
                          aria-label={'Восстановить из ' + backup.filename}
                          onClick={() => onRestore(backup)}
                        >
                          <RotateCcw size={18} />
                        </button>
                        <a className="text-button" href={'/api/backups/' + backup.id + '/manifest'}>
                          Манифест
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
