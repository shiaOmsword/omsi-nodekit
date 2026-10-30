export interface NodeSummary { id: string; name: string; revision: string }
export interface NodeRecord extends NodeSummary { yaml: string }
export type Action = 'check' | 'doctor' | 'fresh' | 'restore' | 'backup';
export interface Job { id: string; node_id: string; action: Action; status: string; created_at: string; error: string | null; backup_id: string | null }
export interface Event { seq: number; message: string; level: string; created_at: string }
export interface JobDetail extends Job { events: Event[] }
export interface Backup { id: string; filename: string; size: number; sha256: string; created_at: string }
export interface Plan { action: Action; revision: string; remote_dir: string; steps: string[]; files: Record<string, string> }
export interface ApiErrorDetail { field?: string; code?: string; [key: string]: unknown }
export interface ApiEnvelope<T> {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string; details: ApiErrorDetail[] } | null;
  meta: { request_id: string };
}
export class ApiError extends Error {
  constructor(message: string, public readonly code: string, public readonly status: number,
    public readonly details: ApiErrorDetail[] = [], public readonly requestId = '') {
    const fields = details.map(item => item.field).filter(Boolean).join(', ');
    super(fields ? `${message}: ${fields}` : message);
    this.name = 'ApiError';
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { 'Content-Type': 'application/json', 'X-Nodekit-Request': '1', ...init?.headers } });
  const body = await response.json().catch(() => null) as ApiEnvelope<T> | null;
  if (!body || typeof body.ok !== 'boolean' || !body.meta || typeof body.meta.request_id !== 'string') {
    throw new ApiError('Сервер вернул неожиданный формат ответа', 'invalid_response', response.status);
  }
  if (!response.ok || !body.ok) {
    throw new ApiError(body.error?.message ?? `HTTP ${response.status}`, body.error?.code ?? 'http_error',
      response.status, body.error?.details ?? [], body.meta.request_id);
  }
  return body.data as T;
}
