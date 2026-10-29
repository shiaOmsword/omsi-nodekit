export interface NodeSummary { id: string; name: string; revision: string }
export interface NodeRecord extends NodeSummary { yaml: string }
export type Action = 'check' | 'doctor' | 'fresh' | 'restore' | 'backup';
export interface Job { id: string; node_id: string; action: Action; status: string; created_at: string; error: string | null; backup_id: string | null }
export interface Event { seq: number; message: string; level: string; created_at: string }
export interface JobDetail extends Job { events: Event[] }
export interface Backup { id: string; filename: string; size: number; sha256: string; created_at: string }
export interface Plan { action: Action; revision: string; remote_dir: string; steps: string[]; files: Record<string, string> }
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', 'X-Nodekit-Request': '1', ...init?.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? `HTTP ${response.status}`));
  }
  return response.json() as Promise<T>;
}
