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
export type Action = 'check' | 'doctor' | 'fresh' | 'restore' | 'backup' | 'configure' | 'inbound' | 'traffic' | 'tunnel' | 'xhttp' | 'client_import' | 'subscription_maintenance' | 'tcp_tuning';
export interface BackupClientCatalog {
  inbounds: {
    id: number;
    remark: string;
    protocol: string;
    client_count: number;
    clients: { ref: string; email: string; enabled: boolean; has_subscription: boolean; restorable: boolean; shared_subscription: boolean; subscription_owner_email: string | null; subscription_owner_refs: string[]; external_link_count: number; external_links_compatible: boolean; depends_on: string[] }[];
  }[];
}
export interface JobOptions {
  tcp_tuning?: { algorithm: "cubic" | "bbr"; expected_fingerprint: string };
  subscription_maintenance?: { id: number; expected_fingerprint: string; mode: 'audit' | 'clear_server_cache'; client_email?: string; acknowledge_restart?: boolean };
  client_import?: { source_inbound_id: number; target_inbound_id: number; expected_fingerprint: string; client_refs: string[]; include_external_links: boolean };
  tunnel?: { name: string; outbound_tag: string; id: number; expected_fingerprint: string; members?: string[]; pool_name?: string };
  inbound?: { id: number; expected_fingerprint: string; operation: 'update' | 'delete' | 'add_client' | 'delete_client'; client_email?: string; remark?: string; port?: number; server_name?: string; close_unmanaged_rule?: boolean };
  traffic?: { id: number; expected_fingerprint: string };
  xhttp?: { operation: 'create' | 'update' | 'publish'; id?: number; expected_fingerprint?: string; remark: string; domain: string; port: number; path: string; mode: 'auto' | 'packet-up' | 'stream-up'; client_email?: string };
}
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
  options?: JobOptions;
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
  client_email?: string | null;
}
export interface DeploymentTarget {
  role: 'ingress' | 'exit';
  panel_runtime: 'native' | 'docker';
  caddy_mode: 'none' | 'docker' | 'existing';
  caddy_id: string | null;
  subscription_bind: string;
  install_docker: boolean;
  manage_ufw?: boolean;
  manage_caddy_ports?: boolean;
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
  inbounds_readable?: boolean;
  inbounds_truncated?: boolean;
  inbounds?: {
    id: number;
    remark: string;
    protocol: string;
    listen: string;
    port: number;
    enabled: boolean;
    network: string;
    security: string;
    client_count: number;
    clients: { email: string; enabled: boolean; has_subscription: boolean }[];
    tag?: string;
    server_names?: string[];
    target?: string;
    fingerprint?: string;
    nodekit_name?: string | null;
    xhttp_path?: string;
    xhttp_mode?: string;
    xhttp_domain?: string | null;
  }[];
}
export type InboundFinding = NonNullable<PanelFinding['inbounds']>[number];
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
  compose_project?: string | null;
  compose_service?: string | null;
  compose_files?: string[];
  compose_working_dir?: string | null;
  bridge_networks?: {name: string; interface: string; subnet: string; gateway: string}[];
}
export interface DeploymentProfileFinding {
  panel_runtime: 'native' | 'docker';
  caddy_runtime: 'none' | 'native' | 'docker';
  required: string[];
  missing: string[];
  ready: boolean;
}
export interface InstallationReport {
  tcp_tuning?: { current: string; available: string[]; managed_algorithm?: string | null; conflict: boolean; fingerprint: string } | null;
  observed_at: string;
  panels: PanelFinding[];
  selected_panel: string | null;
  caddy: CaddyFinding[];
  capabilities: Record<string, boolean>;
  warnings: string[];
  profiles?: DeploymentProfileFinding[];
  ssh_host?: string | null;
  ssh_port?: number | null;
  subscription_checks?: { name: string; state: 'ok' | 'error' | 'warning' | 'not_checked'; detail: string }[];
  subscription_url_template?: string | null;
  firewall?: { state: string; default_incoming?: string | null; default_outgoing?: string | null; default_routed?: string | null; warnings: string[]; rules: {
    number: number; action: string; direction: string; destination: string; source: string; port: string; protocol: string; interface: string | null; ipv6: boolean; managed: boolean;
  }[] } | null;
  network_checks?: { name: string; state: 'ok' | 'error' | 'warning' | 'not_checked'; detail: string }[];
  traffic_checks?: { name: string; state: 'ok' | 'error' | 'warning' | 'not_checked'; detail: string }[];
  tunnels?: { name: string; host: string; ssh_port: number; local_port: number; target_port: number; active: boolean; enabled: boolean }[];
  egress?: { readable: boolean; default_tag?: string | null; outbounds: { tag: string; protocol: string; via: string | null }[];
    rules: {index: number; inbound_tags: string[]; outbound_tag: string; balancer_tag: string; conditional: boolean}[]; warnings: string[] } | null;
}
