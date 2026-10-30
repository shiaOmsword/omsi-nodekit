import { parse, stringify } from 'yaml';
import type { DeploymentTarget, Installation } from '../types';

export interface NodeConfig {
  id: string;
  name: string;
  ssh: {
    host: string;
    port?: number;
    user?: string;
    key_id?: string | null;
    identity_file?: string;
    known_hosts_file?: string;
    sudo?: boolean;
    sudo_password?: string | null;
    sudo_password_env?: string | null;
  };
  panel?: {
    installation?: Installation;
    port?: number;
    base_path?: string;
    subscription_port?: number;
    subscription_path?: string;
    [key: string]: unknown;
  };
  caddy?: { enabled?: boolean; domain?: string; https_port?: number; [key: string]: unknown };
  deployment?: DeploymentTarget | null;
  [key: string]: unknown;
}
export function readConfig(text: string): NodeConfig {
  const data = parse(text, { maxAliasCount: 100 });
  if (
    !data ||
    typeof data !== 'object' ||
    Array.isArray(data) ||
    !data.ssh ||
    typeof data.ssh !== 'object'
  )
    throw new Error('Некорректная конфигурация ноды');
  return data as NodeConfig;
}
export function writeConfig(config: NodeConfig) {
  return stringify(config, { lineWidth: 0 });
}
export function tryConfig(text: string): NodeConfig | null {
  try {
    return readConfig(text);
  } catch {
    return null;
  }
}
export const defaultTarget = (): DeploymentTarget => ({
  role: 'exit',
  panel_runtime: 'native',
  caddy_mode: 'none',
  caddy_id: null,
  subscription_bind: '127.0.0.1',
  install_docker: false,
  inbounds: [],
});

export function preserveDeploymentIntent(
  original: string,
  suggested: string,
  panelAbsent: boolean,
) {
  const previous = readConfig(original);
  const next = readConfig(suggested);
  if (panelAbsent && previous.deployment && next.deployment) {
    const runtime =
      previous.deployment.role === next.deployment.role
        ? previous.deployment.panel_runtime
        : next.deployment.panel_runtime;
    next.deployment = {
      ...next.deployment,
      panel_runtime: runtime,
      inbounds: previous.deployment.inbounds,
      install_docker:
        previous.deployment.install_docker &&
        (runtime === 'docker' || next.deployment.caddy_mode === 'docker'),
    };
  }
  return writeConfig(next);
}
