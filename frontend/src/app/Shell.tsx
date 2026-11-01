import { useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  Archive,
  BookOpen,
  ChevronRight,
  FileText,
  KeyRound,
  LayoutDashboard,
  Menu,
  Network,
  Plus,
  Server,
  WifiOff,
  X,
} from 'lucide-react';
import type { Route } from '../framework/navigation/router';
import type { NodeSummary } from '../types';
import { Button } from '../framework/components';

const navigation = [
  { path: '/dashboard', page: 'dashboard', label: 'Обзор', icon: LayoutDashboard },
  { path: '/nodes', page: 'nodes', label: 'Ноды', icon: Server },
  { path: '/operations', page: 'operations', label: 'Операции', icon: Activity },
  { path: '/backups', page: 'backups', label: 'Бэкапы', icon: Archive },
  { path: '/keys', page: 'keys', label: 'SSH-ключи', icon: KeyRound },
  { path: '/logs', page: 'logs', label: 'Логи', icon: FileText },
  { path: '/help', page: 'help', label: 'Справка', icon: BookOpen },
] as const;

export function Shell({
  route,
  nodes,
  online,
  navigate,
  onCreate,
  children,
}: {
  route: Route;
  nodes: NodeSummary[];
  online: boolean;
  navigate: (path: string) => void;
  onCreate: () => void;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const selectedPage = route.page === 'node' ? 'nodes' : route.page;
  const node = route.page === 'node' ? nodes.find((n) => n.id === route.id) : null;
  const title = navigation.find((n) => n.page === selectedPage)?.label || 'Страница';
  function link(event: React.MouseEvent, path: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      return;
    event.preventDefault();
    navigate(path);
    setMobileOpen(false);
  }
  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <div className="sidebar-brand-row">
          <a className="workspace-brand" href="#/dashboard" onClick={(e) => link(e, '/dashboard')}>
            <span className="brand-symbol">
              <Network size={22} />
            </span>
            <span>
              Nodekit<small>OMSI</small>
            </span>
          </a>
          <button
            type="button"
            className="mobile-nav-toggle"
            aria-expanded={mobileOpen}
            aria-controls="workspace-navigation"
            onClick={() => setMobileOpen((value) => !value)}
          >
            {mobileOpen ? <X size={19} /> : <Menu size={19} />}Разделы
          </button>
        </div>
        <div className="workspace-caption">Рабочее пространство</div>
        <nav
          id="workspace-navigation"
          aria-label="Разделы панели"
          className={'main-navigation' + (mobileOpen ? ' expanded' : '')}
        >
          {navigation.map((item, index) => (
            <div key={item.page}>
              {index === 3 && <div className="nav-section-label">Управление</div>}
              {index === 5 && <div className="nav-section-label">Система</div>}
              <a
                href={'#' + item.path}
                onClick={(e) => link(e, item.path)}
                aria-current={selectedPage === item.page ? 'page' : undefined}
                className={selectedPage === item.page ? 'selected' : ''}
              >
                <item.icon size={19} />
                <span>{item.label}</span>
                {item.page === 'nodes' && <span className="nav-count">{nodes.length}</span>}
              </a>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <Button full onClick={onCreate} icon={<Plus size={17} />}>
            Добавить ноду
          </Button>
          <div className={'api-connection' + (!online ? ' offline' : '')}>
            {online ? <span className="status-dot" /> : <WifiOff size={14} />}
            <span>{online ? 'Локальный API доступен' : 'Нет связи с API'}</span>
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="workspace-topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <ChevronRight size={14} />
            <a href={'#/' + selectedPage} onClick={(e) => link(e, '/' + selectedPage)}>
              {title}
            </a>
            {node && (
              <>
                <ChevronRight size={14} />
                <strong>{node.name}</strong>
              </>
            )}
          </div>
          <span className="local-chip">
            <span className="status-dot" />
            Локально
          </span>
        </header>
        <main
          className="workspace-content"
          id="main-content"
          key={route.page === 'node' ? route.id : route.page}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
