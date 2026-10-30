import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { ConnectionSettings } = compiled('features/nodes/ConnectionSettings.js');
const { SSHKeysPanel } = compiled('features/keys/SSHKeysPanel.js');
const { HelpPanel } = compiled('features/help/HelpPanel.js');
const { InstallationReportView } = compiled('features/nodes/InstallationReportView.js');
const { messages } = compiled('framework/messages/index.js');
const { guides } = compiled('features/help/guides.js');
const noop = () => {};

test('connection selectors preserve key and installation selection with accessible labels', () => {
  const html = renderToStaticMarkup(React.createElement(ConnectionSettings, {
    draft: { ssh: { key_id: 'key-id' }, panel: { installation: 'native' } },
    keys: [{ id: 'key-id', name: 'Москва', fingerprint: 'SHA256:public-fingerprint' }],
    busy: false, onKey: noop, onInstallation: noop, onManage: noop, onHelp: noop,
  }));
  assert.match(html, /value="native" selected=""/);
  assert.match(html, /value="key-id" selected=""/);
  assert.ok(html.includes(messages.connection.readOnly));
  assert.ok(html.includes(messages.connection.key));
});

test('invalid YAML disables connection selectors without replacing the draft', () => {
  const html = renderToStaticMarkup(React.createElement(ConnectionSettings, {
    draft: null, keys: [], busy: false, onKey: noop, onInstallation: noop, onManage: noop, onHelp: noop,
  }));
  assert.equal((html.match(/<select disabled=""/g) || []).length, 2);
  assert.ok(html.includes(messages.connection.invalidYaml));
});

test('key manager shows copyable public material and a real submit form', () => {
  const html = renderToStaticMarkup(React.createElement(SSHKeysPanel, {
    keys: [{ id: 'key-id', name: '<script>unsafe</script>', public_key: 'ssh-ed25519 PUBLIC fixture', fingerprint: 'SHA256:fingerprint' }],
    refresh: async () => {}, onUse: noop, onHelp: noop,
  }));
  assert.ok(html.includes('ssh-ed25519 PUBLIC fixture'));
  assert.ok(html.includes('type="submit"'));
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(!html.includes('BEGIN OPENSSH PRIVATE KEY'));
  assert.ok(html.includes(messages.keys.passphrase));
});

test('all in-panel guides are reachable and SSH setup distinguishes host and client keys', () => {
  assert.deepEqual(guides.map(guide => guide.id), ['start', 'ssh', 'native', 'docker', 'certificates', 'recovery', 'failures']);
  for (const guide of guides) {
    const html = renderToStaticMarkup(React.createElement(HelpPanel, { selected: guide.id, onSelect: noop, onBack: noop }));
    assert.ok(html.includes(guide.title));
    assert.ok(html.includes('aria-current="page"'));
    assert.ok(guide.steps.length >= 4);
  }
  assert.ok(guides.find(guide => guide.id === 'ssh').steps.join(' ').includes('fingerprint сервера'));
});

test('inventory renders certificate dates, shared networks and route topology', () => {
  const report = {
    observed_at: '2026-10-30T09:00:00Z', selected_panel: 'native:x-ui', capabilities: { docker: false }, warnings: [],
    panels: [{ id: 'native:x-ui', installation: 'native', active: true, service: 'x-ui', database_path: '/etc/x-ui/x-ui.db',
      settings: { webPort: '8443' }, defaulted_settings: [], warnings: [], network_mode: null,
      certificates: [{ usage: 'panel', state: 'valid', cert_path: '/root/cert.pem', key_path: '/root/private.key', not_after: '2027-01-01T00:00:00Z', key_readable: true }],
    }],
    caddy: [{ id: 'docker:caddy', installation: 'docker', active: true, container: 'caddy', config_path: '/etc/caddy/Caddyfile',
      network_mode: 'bridge', networks: ['proxy-net'], published_ports: ['0.0.0.0:2096->443/tcp'], warnings: [],
      routes: [{ listen: [':443'], hosts: ['vpn.example.com'], paths: ['/sub/*'], upstreams: ['panel:2097'] }],
    }],
  };
  const html = renderToStaticMarkup(React.createElement(InstallationReportView, { report, node: 'test-node' }));
  for (const text of ['proxy-net', 'panel:2097', 'vpn.example.com', '/root/cert.pem', '2027-01-01', messages.report.selected, messages.report.metadataOnly]) {
    assert.ok(html.includes(text), text);
  }
  assert.ok(html.includes('<table>'));
});
