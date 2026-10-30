import { useEffect, useRef, useState } from 'react';
import type { Action } from '../../types';

export type Route =
  | { page: 'dashboard' | 'nodes' | 'backups' | 'keys' | 'help' }
  | {
      page: 'node';
      id: string;
      tab: 'overview' | 'operations' | 'config' | 'history';
      action?: Action;
    }
  | { page: 'operations' | 'logs'; id?: string }
  | { page: 'not-found' };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (!parts.length || (parts[0] === 'dashboard' && parts.length === 1))
    return { page: 'dashboard' };
  if (parts[0] === 'nodes' && parts.length > 1) {
    const [, id, tab = 'overview', action] = parts;
    if (
      !/^[a-z][a-z0-9-]{0,39}$/.test(id) ||
      !['overview', 'operations', 'config', 'history'].includes(tab)
    )
      return { page: 'not-found' };
    if (
      parts.length > 4 ||
      (action &&
        (tab !== 'operations' ||
          !['check', 'doctor', 'fresh', 'restore', 'backup'].includes(action)))
    )
      return { page: 'not-found' };
    return { page: 'node', id, tab: tab as 'overview', action: action as Action | undefined };
  }
  if (['operations', 'logs'].includes(parts[0]) && parts.length <= 2) {
    if (parts[1] && !/^[a-f0-9]{32}$/.test(parts[1])) return { page: 'not-found' };
    return { page: parts[0] as 'operations', id: parts[1] };
  }
  if (parts.length === 1 && ['nodes', 'backups', 'keys', 'help'].includes(parts[0]))
    return { page: parts[0] as 'nodes' };
  return { page: 'not-found' };
}

export function useWorkspaceRoute(dirty: boolean) {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  const [pending, setPending] = useState<string | null>(null);
  const current = useRef(window.location.hash || '#/dashboard');
  const blocked = useRef(dirty);
  blocked.current = dirty;
  function commit(path: string) {
    const hash = path.startsWith('#') ? path : '#' + path;
    if (hash !== window.location.hash) window.history.pushState(null, '', hash);
    current.current = hash;
    setRoute(parseRoute(hash));
    window.scrollTo({ top: 0 });
  }
  function navigate(path: string) {
    const hash = path.startsWith('#') ? path : '#' + path;
    if (hash === current.current) return;
    if (blocked.current) setPending(hash);
    else commit(hash);
  }
  useEffect(() => {
    const change = () => {
      const next = window.location.hash || '#/dashboard';
      if (blocked.current && next !== current.current) {
        window.history.replaceState(null, '', current.current);
        setPending(next);
      } else {
        current.current = next;
        setRoute(parseRoute(next));
        window.scrollTo({ top: 0 });
      }
    };
    const leave = (event: BeforeUnloadEvent) => {
      if (blocked.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('hashchange', change);
    window.addEventListener('beforeunload', leave);
    return () => {
      window.removeEventListener('hashchange', change);
      window.removeEventListener('beforeunload', leave);
    };
  }, []);
  return {
    route,
    navigate,
    pending,
    cancel: () => setPending(null),
    discard: () => {
      if (pending) commit(pending);
      setPending(null);
    },
  };
}
