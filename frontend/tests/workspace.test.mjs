import test from 'node:test';
import assert from 'node:assert/strict';
import { compiled } from './helpers/compiled.mjs';
const { parseRoute } = compiled('framework/navigation/router.js');
const { readConfig, writeConfig, preserveDeploymentIntent } = compiled('app/config.js');
const { timestamp } = compiled('app/format.js');

test('global sections and node operations have independent deep links', () => {
  assert.deepEqual(parseRoute(''), { page: 'dashboard' });
  for (const page of ['nodes', 'backups', 'keys', 'help', 'logs', 'operations'])
    assert.equal(parseRoute('#/' + page).page, page);
  assert.deepEqual(parseRoute('#/nodes/eu-1/operations/restore'), {
    page: 'node',
    id: 'eu-1',
    tab: 'operations',
    action: 'restore',
  });
  assert.equal(parseRoute('#/logs/' + 'a'.repeat(32)).id, 'a'.repeat(32));
});
test('malformed routes never become an operation', () => {
  for (const hash of [
    '#/nodes/../../ops',
    '#/nodes/eu/operations/delete',
    '#/nodes/eu/config/restore',
    '#/logs/not-an-id',
    '#/backups/extra',
  ])
    assert.equal(parseRoute(hash).page, 'not-found');
});
test('YAML editing preserves string sudo passwords and unrelated settings', () => {
  const config = readConfig(
    'id: test\nname: Test\nssh:\n  host: example.com\n  sudo: true\n  sudo_password: "00123"\ntunnels:\n  - name: original\n    local_port: 15443\n',
  );
  config.name = 'Новое имя';
  const roundTrip = readConfig(writeConfig(config));
  assert.equal(roundTrip.ssh.sudo_password, '00123');
  assert.deepEqual(roundTrip.tunnels, config.tunnels);
});
test('invalid config roots are rejected instead of silently becoming a node', () => {
  for (const text of ['null', '[]', 'name: missing-ssh']) assert.throws(() => readConfig(text));
});
test('server timestamps handle naive UTC and already qualified values', () => {
  assert.equal(timestamp('2026-10-30 15:00:00').toISOString(), '2026-10-30T15:00:00.000Z');
  assert.equal(timestamp('2026-10-30T15:00:00Z').toISOString(), '2026-10-30T15:00:00.000Z');
  assert.equal(timestamp('2026-10-30T18:00:00+03:00').toISOString(), '2026-10-30T15:00:00.000Z');
});

test('discovery keeps manually configured inbounds while updating detected Caddy metadata', () => {
  const original = writeConfig({
    id: 'exit',
    name: 'Exit',
    ssh: { host: 'example.com', sudo_password: '00123' },
    deployment: {
      role: 'exit',
      panel_runtime: 'docker',
      caddy_mode: 'none',
      inbounds: [{ name: 'ssh', port: 8443, server_name: 'target.example.com' }],
      install_docker: true,
    },
  });
  const suggested = writeConfig({
    id: 'exit',
    name: 'Exit',
    ssh: { host: 'example.com', sudo_password: '00123' },
    deployment: {
      role: 'exit',
      panel_runtime: 'native',
      caddy_mode: 'existing',
      caddy_id: 'docker:detected',
      subscription_bind: '172.18.0.1',
      inbounds: [],
      install_docker: false,
    },
  });
  const result = readConfig(preserveDeploymentIntent(original, suggested, true));
  assert.equal(result.deployment.panel_runtime, 'docker');
  assert.equal(result.deployment.caddy_id, 'docker:detected');
  assert.equal(result.deployment.inbounds[0].port, 8443);
  assert.equal(result.ssh.sudo_password, '00123');
});
test('discovery of an existing panel does not reattach a fresh-deployment target', () => {
  const original = 'id: node\nname: Test\nssh:\n  host: example.com\ndeployment:\n  role: exit\n';
  const suggested =
    'id: node\nname: Test\nssh:\n  host: example.com\npanel:\n  installation: native\n';
  assert.equal(
    readConfig(preserveDeploymentIntent(original, suggested, false)).deployment,
    undefined,
  );
});
