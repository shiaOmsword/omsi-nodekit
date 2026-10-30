import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../framework/api';
import { getNodeErrorMessage } from '../features/nodes/configErrors';
import type {
  Backup,
  DraftConfig,
  Job,
  JobDetail,
  NodeRecord,
  NodeState,
  NodeSummary,
  SSHKey,
} from '../types';
import { tryConfig } from './config';

export function useWorkspace() {
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [keys, setKeys] = useState<SSHKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<NodeRecord | null>(null);
  const [yaml, setYaml] = useState('');
  const [draft, setDraft] = useState<DraftConfig | null>(null);
  const [nodeLoading, setNodeLoading] = useState(false);
  const nodeId = useRef<string | null>(null);
  const mutationRunning = useRef(false);
  const refresh = useCallback(async () => {
    const [nodeList, jobList, backupList, keyList] = await Promise.all([
      api<NodeSummary[]>('/nodes'),
      api<Job[]>('/jobs'),
      api<Backup[]>('/backups'),
      api<SSHKey[]>('/ssh-keys'),
    ]);
    setNodes(nodeList);
    setJobs(jobList);
    setBackups(backupList);
    setKeys(keyList);
    setOnline(true);
  }, []);
  useEffect(() => {
    let alive = true;
    const poll = async (initial = false) => {
      try {
        await refresh();
      } catch (err) {
        if (alive) {
          setOnline(false);
          if (initial) setError(getNodeErrorMessage(err));
        }
      } finally {
        if (alive) setLoading(false);
      }
    };
    void poll(true);
    const timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') void poll();
    }, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [refresh]);

  const selectNode = useCallback((id: string | null) => {
    const controller = new AbortController();
    nodeId.current = id;
    setSelected(null);
    setYaml('');
    setDraft(null);
    setError('');
    setNodeLoading(!!id);
    if (id)
      api<NodeRecord>('/nodes/' + id, { signal: controller.signal })
        .then((record) => {
          if (!controller.signal.aborted) {
            setSelected(record);
            setYaml(record.yaml);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(getNodeErrorMessage(err));
        })
        .finally(() => {
          if (!controller.signal.aborted) setNodeLoading(false);
        });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setDraft(null);
    if (!yaml) return () => controller.abort();
    const timer = setTimeout(() => {
      api<{ node: DraftConfig }>('/config/validate', {
        method: 'POST',
        body: JSON.stringify({ yaml }),
        signal: controller.signal,
      })
        .then((result) => {
          if (!controller.signal.aborted) setDraft(result.node);
        })
        .catch(() => {});
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [yaml]);
  async function run<T>(task: () => Promise<T>): Promise<T | undefined> {
    if (mutationRunning.current) return undefined;
    mutationRunning.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      return await task();
    } catch (err) {
      setError(getNodeErrorMessage(err));
      return undefined;
    } finally {
      mutationRunning.current = false;
      setBusy(false);
    }
  }
  async function saveNode(text: string, expectedId?: string) {
    const result = await api<{ node: { id: string } }>('/config/validate', {
      method: 'POST',
      body: JSON.stringify({ yaml: text }),
    });
    if (expectedId && result.node.id !== expectedId)
      throw new Error('ID существующей ноды менять нельзя');
    const record = await api<NodeRecord>('/nodes/' + result.node.id, {
      method: 'PUT',
      body: JSON.stringify({ yaml: text }),
    });
    if (nodeId.current === record.id) {
      setSelected(record);
      setYaml(record.yaml);
    }
    await refresh();
    setNotice('Настройки ноды сохранены');
    return record;
  }
  async function changeState(id: string, state: NodeState) {
    const record = await api<NodeRecord>('/nodes/' + id + '/state', {
      method: 'PATCH',
      body: JSON.stringify({ state }),
    });
    if (nodeId.current === id) setSelected(record);
    await refresh();
    setNotice('Статус ноды изменён');
    return record;
  }
  return {
    nodes,
    jobs,
    backups,
    keys,
    selected,
    yaml,
    setYaml,
    draft,
    config: tryConfig(yaml),
    dirty: !!selected && yaml !== selected.yaml,
    loading,
    nodeLoading,
    online,
    busy,
    error,
    setError,
    notice,
    setNotice,
    refresh,
    selectNode,
    run,
    saveNode,
    changeState,
  };
}
export type Workspace = ReturnType<typeof useWorkspace>;

export function useJobDetail(id: string | undefined) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setJob(null);
    setError('');
    if (!id) return () => controller.abort();
    const load = () =>
      api<JobDetail>('/jobs/' + id, { signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted) {
            setJob(result);
            setError('');
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError(getNodeErrorMessage(err));
        });
    void load();
    const timer = setInterval(load, 2000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [id]);
  return { job, error };
}

export function useNodeReport(id: string | null, jobs: Job[]) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const candidates = jobs.filter((j) => j.node_id === id).slice(0, 6);
  const key = candidates.map((j) => j.id + ':' + j.status).join(',');
  useEffect(() => {
    const controller = new AbortController();
    setJob(null);
    if (id && key)
      Promise.all(
        key
          .split(',')
          .map((value) =>
            api<JobDetail>('/jobs/' + value.split(':')[0], { signal: controller.signal }).catch(
              () => null,
            ),
          ),
      ).then((results) => {
        if (!controller.signal.aborted) setJob(results.find((result) => result?.report) || null);
      });
    return () => controller.abort();
  }, [id, key]);
  return job;
}
