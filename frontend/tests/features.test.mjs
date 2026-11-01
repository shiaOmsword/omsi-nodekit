import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { NodeFormModal } = compiled('features/nodes/NodeFormModal.js');
const { SSHKeysPanel } = compiled('features/keys/SSHKeysPanel.js');
const { HelpPanel } = compiled('features/help/HelpPanel.js');
const { InstallationReportView } = compiled('features/nodes/InstallationReportView.js');
const { messages } = compiled('framework/messages/index.js');
const { guides } = compiled('features/help/guides.js');
const noop = () => {};
const template =
  'id: test-node\nname: Test\nssh:\n  host: 203.0.113.10\n  key_id: key-id\n  sudo: true\n  sudo_password: "00123"\npanel:\n  installation: native\n';

test('node settings use the shared dialog and preserve SSH and installation selection', () => {
  const html = renderToStaticMarkup(
    React.createElement(NodeFormModal, {
      record: { id: 'test-node', name: 'Test', yaml: template },
      template,
      nodes: [],
      keys: [{ id: 'key-id', name: 'Москва', fingerprint: 'SHA256:fixture' }],
      busy: false,
      error: '',
      onClose: noop,
      onSave: noop,
    }),
  );
  assert.match(html, /<dialog/);
  assert.match(html, /aria-modal="true"/);
  assert.match(html, /value="native" selected=""/);
  assert.match(html, /value="key-id" selected=""/);
  assert.match(html, /type="password"/);
  assert.match(html, /value="00123"/);
  for (const [, pattern] of html.matchAll(/pattern="([^"]+)"/g)) {
    assert.doesNotThrow(() => new RegExp(pattern, 'v'));
  }
  assert.ok(html.includes('Сохранить настройки'));
  assert.ok(html.includes('disabled="" value="test-node"') || html.includes('disabled=""'));
});

test('key page offers modal actions and escapes public key names', () => {
  const html = renderToStaticMarkup(
    React.createElement(SSHKeysPanel, {
      keys: [
        {
          id: 'key-id',
          name: '<script>unsafe</script>',
          public_key: 'ssh-ed25519 PUBLIC fixture',
          fingerprint: 'SHA256:fixture',
          created_at: '2026-10-30T09:00:00Z',
        },
      ],
      onCreate: noop,
      onDelete: noop,
      onUse: noop,
      onHelp: noop,
    }),
  );
  assert.ok(html.includes('ssh-ed25519 PUBLIC fixture'));
  assert.ok(html.includes('Создать ключ'));
  assert.ok(html.includes('Назначить ноде'));
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(!html.includes('BEGIN OPENSSH PRIVATE KEY'));
  assert.ok(html.includes(messages.keys.passphrase));
});

test('all existing guides remain reachable', () => {
  assert.deepEqual(
    guides.map((guide) => guide.id),
    ['start', 'ssh', 'native', 'docker', 'certificates', 'recovery', 'xhttp', 'tunnel-pool', 'recovery-audit', 'failures'],
  );
  for (const guide of guides) {
    const html = renderToStaticMarkup(
      React.createElement(HelpPanel, { selected: guide.id, onSelect: noop, onBack: noop }),
    );
    assert.ok(html.includes(guide.title));
    assert.ok(html.includes('aria-current="page"'));
    assert.ok(guide.steps.length >= 4);
  }
  assert.ok(
    guides
      .find((g) => g.id === 'ssh')
      .steps.join(' ')
      .includes('fingerprint сервера'),
  );
});

test('inventory leads with a readable summary and retains network and TLS evidence in details', () => {
  const report = {
    observed_at: '2026-10-30T09:00:00Z',
    selected_panel: 'native:x-ui',
    capabilities: { docker: false },
    warnings: [],
    panels: [
      {
        id: 'native:x-ui',
        installation: 'native',
        active: true,
        service: 'x-ui',
        database_path: '/etc/x-ui/x-ui.db',
        settings: { webPort: '8443' },
        defaulted_settings: [],
        warnings: [],
        network_mode: null,
        certificates: [
          {
            usage: 'panel',
            state: 'valid',
            cert_path: '/root/cert.pem',
            key_path: '/root/private.key',
            not_after: '2027-01-01T00:00:00Z',
            key_readable: true,
          },
        ],
      },
    ],
    caddy: [
      {
        id: 'docker:caddy',
        installation: 'docker',
        active: true,
        container: 'caddy',
        config_path: '/etc/caddy/Caddyfile',
        network_mode: 'bridge',
        networks: ['proxy-net'],
        published_ports: ['0.0.0.0:2096->443/tcp'],
        warnings: [],
        routes: [
          {
            listen: [':443'],
            hosts: ['vpn.example.com'],
            paths: ['/sub/*'],
            upstreams: ['panel:2097'],
          },
        ],
      },
    ],
  };
  const html = renderToStaticMarkup(
    React.createElement(InstallationReportView, { report, node: 'test-node' }),
  );
  for (const text of [
    'Состояние сервера',
    'proxy-net',
    'panel:2097',
    'vpn.example.com',
    '/root/cert.pem',
    '2027-01-01',
    messages.report.selected,
    messages.report.metadataOnly,
  ])
    assert.ok(html.includes(text), text);
  assert.ok(html.indexOf('report-summary') < html.indexOf('Системные инструменты'));
  assert.ok(html.includes('<details'));
});
