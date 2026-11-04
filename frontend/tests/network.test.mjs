import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { parse, stringify } from 'yaml';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { InboundModal } = compiled('features/nodes/InboundModal.js');
const { InboundReport } = compiled('features/nodes/SubscriptionReport.js');
const { NetworkReport } = compiled('features/nodes/NetworkReport.js');
const { PlanModal } = compiled('features/operations/PlanModal.js');
const { parseRoute } = compiled('framework/navigation/router.js');
const { preserveDeploymentIntent } = compiled('app/config.js');
const noop = () => {};
const record = { id: 'ultra', name: 'Ultra' };
const inbound = { id: 1, remark: 'Test inbound', port: 8443, listen: '0.0.0.0', enabled: true,
  protocol: 'vless', network: 'tcp', security: 'reality', server_names: ['example.com'],
  target: 'example.com:443', fingerprint: 'a'.repeat(64), client_count: 1, clients: [] };

test('inbound and network tabs have direct routes', () => {
  assert.equal(parseRoute('#/nodes/ultra/inbounds').tab, 'inbounds');
  assert.equal(parseRoute('#/nodes/ultra/network').tab, 'network');
});

test('inbound edits use a preview and deletion requires an explicit confirmation', () => {
  const props = { record, inbound, busy: false, error: '', onClose: noop, onPreview: noop };
  const edit = renderToStaticMarkup(React.createElement(InboundModal, { ...props, remove: false }));
  assert.ok(edit.includes('value="8443"') && edit.includes('value="example.com"'));
  assert.ok(edit.includes('Посмотреть план'));
  const remove = renderToStaticMarkup(React.createElement(InboundModal, { ...props, remove: true }));
  assert.match(remove, /<input(?=[^>]*type="checkbox")(?=[^>]*required)[^>]*>/);
  assert.ok(remove.includes('Удалить inbound и всех его клиентов'));
});

test('old reports cannot edit or probe without a current fingerprint', () => {
  const html = renderToStaticMarkup(React.createElement(InboundReport, {
    panel: { inbounds_readable: true, inbounds: [{ ...inbound, fingerprint: undefined }] },
    onEdit: noop, onDelete: noop, onTest: noop,
  }));
  assert.equal([...html.matchAll(/<button[^>]*disabled/g)].length, 3);
});

test('network report shows policy mismatches, actual outbound protocol and failed traffic', () => {
  const html = renderToStaticMarkup(React.createElement(NetworkReport, { report: {
    caddy: [], firewall: { state: 'active', default_incoming: 'deny', default_outgoing: 'allow', default_routed: 'deny', rules: [], warnings: [] },
    network_checks: [{ name: 'caddy_port', state: 'warning', detail: '2096 не опубликован' }],
    egress: { readable: true, default_tag: 'From_MSK', outbounds: [{ tag: 'From_MSK', protocol: 'vless' }], rules: [], warnings: [] },
    traffic_checks: [{ name: 'inbound', state: 'error', detail: 'TLS handshake' }],
  } }));
  for (const text of ['2096 не опубликован', 'From_MSK', 'vless', 'TLS handshake', 'исходящие — allow']) assert.ok(html.includes(text));
});

test('delete and traffic plans explain their actual effects', () => {
  const props = { record, busy: false, error: '', onClose: noop, onReload: noop, onLaunch: noop };
  const html = renderToStaticMarkup(React.createElement(PlanModal, { ...props, action: 'inbound',
    plan: { remote_dir: '/opt/omsi-nodekit/ultra', files: {}, steps: [], options: { inbound: { operation: 'delete' } } } }));
  assert.ok(html.includes('Удаление inbound: план') && html.includes('Изменяет сервер'));
  const traffic = renderToStaticMarkup(React.createElement(PlanModal, { ...props, action: 'traffic', plan: { remote_dir: '/opt/omsi-nodekit/ultra', files: {}, steps: [] } }));
  assert.ok(traffic.includes('пробный трафик учитывается'));
});

test('rediscovery preserves explicit network automation preferences', () => {
  const previous = { id: 'ultra', name: 'Ultra', ssh: { host: 'example.com' }, deployment: { panel_runtime: 'docker', caddy_mode: 'existing', manage_ufw: false, manage_caddy_ports: false, inbounds: [] } };
  const next = { id: 'ultra', name: 'Ultra', ssh: { host: 'example.com' }, panel: { installation: 'managed' }, deployment: { panel_runtime: 'docker', caddy_mode: 'existing' } };
  const result = parse(preserveDeploymentIntent(stringify(previous), stringify(next), true));
  assert.equal(result.deployment.manage_ufw, false);
  assert.equal(result.deployment.manage_caddy_ports, false);
});

test('TCP BBR action has a dedicated route and warns about socket scope', () => {
  assert.equal(parseRoute('#/nodes/ultra/operations/tcp_tuning').action, 'tcp_tuning');
  const props = { record, busy: false, error: '', onClose: noop, onReload: noop, onLaunch: noop };
  const html = renderToStaticMarkup(React.createElement(PlanModal, { ...props, action: 'tcp_tuning',
    plan: { remote_dir: '/opt/nodekit/test-node', files: {}, steps: [], options: {
      tcp_tuning: { algorithm: 'bbr', expected_fingerprint: 'a'.repeat(64) },
    } } }));
  assert.ok(html.includes('Изменяет сервер'));
  assert.ok(html.includes('Действующие SSH-сессии'));
});

const { BenchmarkComparison, comparable } = compiled('features/nodes/NetworkBenchmarkPanel.js');
test('network comparison never calls missing ICMP healthy or compares different targets', () => {
  const report = { observed_at: '2026-11-03T10:00:00Z', scope: 'vps_direct_https_download',
    algorithm: 'bbr', profile: { url: 'https://example.com/test', attempts: 3 },
    resolved_addresses: ['203.0.113.1'], samples: [], warnings: ['icmp_unavailable'],
    metrics: { mbps: null, rtt_ms: null, jitter_ms: null, loss_percent: null },
    assessment: { mbps: 'unavailable', rtt_ms: 'unavailable', jitter_ms: 'unavailable', loss_percent: 'unavailable' }, host_tcp: null };
  assert.equal(comparable(report, { ...report, algorithm: 'cubic' }), true);
  assert.equal(comparable(report, { ...report, resolved_addresses: ['203.0.113.2'] }), false);
  const html = renderToStaticMarkup(React.createElement(BenchmarkComparison, { reports: [report, { ...report, scope: 'other' }] }));
  assert.ok(html.includes('Недоступно') && html.includes('Сравнение до/после недоступно'));
  assert.ok(!html.includes('В пределах цели'));
});
