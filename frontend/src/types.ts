export interface NodeSummary { id: string; name: string; revision: string }
export interface NodeRecord extends NodeSummary { yaml: string }
export type Action = 'check' | 'doctor' | 'fresh' | 'restore' | 'backup';
export interface Job { id: string; node_id: string; action: Action; status: string; created_at: string; error: string | null; backup_id: string | null }
export interface Event { seq: number; message: string; level: string; created_at: string }
export interface JobDetail extends Job { events: Event[] }
export interface Backup { id: string; filename: string; size: number; sha256: string; created_at: string }
export interface Plan { action: Action; revision: string; remote_dir: string; steps: string[]; files: Record<string, string> }
