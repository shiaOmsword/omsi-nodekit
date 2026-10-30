export type NodeState = 'active' | 'hidden' | 'archived';
export interface NodeSummary {
  id: string;
  name: string;
  revision: string;
  state: NodeState;
}
export interface NodeRecord extends NodeSummary {
  yaml: string;
}
export type Action = 'check' | 'doctor' | 'fresh' | 'restore' | 'backup';
export interface Job {
  id: string;
  node_id: string;
  action: Action;
  status: string;
  created_at: string;
  finished_at?: string | null;
  error: string | null;
  backup_id: string | null;
}
export interface Event {
  seq: number;
  message: string;
  level: string;
  created_at: string;
}
export interface JobDetail extends Job {
  events: Event[];
  report: InstallationReport | null;
}
export interface Backup {
  id: string;
  filename: string;
  size: number;
  sha256: string;
  created_at: string;
}
export interface Plan {
  action: Action;
  revision: string;
  remote_dir: string;
  steps: string[];
  files: Record<string, string>;
}

export type Installation = 'managed' | 'auto' | 'native' | 'docker';
export interface SSHKey {
  id: string;
  name: string;
  public_key: string;
  fingerprint: string;
  created_at: string;
}
export interface TunnelInbound {
  name: string;
  port: number;
  listen: '127.0.0.1' | '0.0.0.0';
  server_name: string;
  target_port: number;
}
export interface DeploymentTarget {
  role: 'ingress' | 'exit';
  panel_runtime: 'native' | 'docker';
  caddy_mode: 'none' | 'docker' | 'existing';
  caddy_id: string | null;
  subscription_bind: string;
  install_docker: boolean;
  inbounds: TunnelInbound[];
}
export interface DiscoveryChoice {
  panel_id: string | null;
  caddy_id: string | null;
  role: 'ingress' | 'exit';
}
export interface DraftConfig {
  ssh: { key_id: string | null; host: string; port: number };
  panel: { installation: Installation };
  deployment: DeploymentTarget | null;
}
export interface CertificateFinding {
  usage: string;
  cert_path: string;
  key_path: string;
  state: string;
  key_readable: boolean | null;
  not_before: string | null;
  not_after: string | null;
  sha256: string | null;
}
export interface PanelFinding {
  id: string;
  installation: string;
  active: boolean;
  service: string | null;
  container: string | null;
  image: string | null;
  database_path: string | null;
  settings: Record<string, string>;
  defaulted_settings: string[];
  certificates: CertificateFinding[];
  network_mode: string | null;
  networks: string[];
  published_ports: string[];
  warnings: string[];
}
export interface ProxyRoute {
  listen: string[];
  hosts: string[];
  paths: string[];
  upstreams: string[];
}
export interface CaddyFinding {
  id: string;
  installation: string;
  active: boolean;
  service: string | null;
  container: string | null;
  image: string | null;
  config_path: string | null;
  config_source: string;
  network_mode: string | null;
  networks: string[];
  published_ports: string[];
  routes: ProxyRoute[];
  warnings: string[];
  host_gateway?: string | null;
}
export interface DeploymentProfileFinding {
  panel_runtime: 'native' | 'docker';
  caddy_runtime: 'none' | 'native' | 'docker';
  required: string[];
  missing: string[];
  ready: boolean;
}
export interface InstallationReport {
  observed_at: string;
  panels: PanelFinding[];
  selected_panel: string | null;
  caddy: CaddyFinding[];
  capabilities: Record<string, boolean>;
  warnings: string[];
  profiles?: DeploymentProfileFinding[];
  ssh_host?: string | null;
  ssh_port?: number | null;
}
