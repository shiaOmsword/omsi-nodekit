import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { stringify } from 'yaml';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { TunnelModal } = compiled('features/nodes/TunnelModal.js');
const { PlanModal } = compiled('features/operations/PlanModal.js');
const noop = () => {};
const record = { id: 'ultra', name: 'Ultra', yaml: stringify({ tunnels: [
  { name: 'gb', host: '203.0.113.20', ssh_port: 2222, local_port: 15443, target_port: 8443 },
] }) };
const inbound = { id: 1, tag: 'in-xhttp', remark: '<phone>', port: 10080, network: 'xhttp', enabled: true, fingerprint: 'a'.repeat(64) };
const report = { selected_panel: 'managed:ultra', panels: [{ id: 'managed:ultra', installation: 'managed', inbounds: [inbound] }],
  egress: { outbounds: [{ tag: '<gb-exit>', protocol: 'vless' }, { tag: 'direct', protocol: 'freedom' }, { tag: 'ssh-ultra-gb', protocol: 'vless' }] } };
const common = { busy: false, error: '', onClose: noop };

test('SSH modal accepts XHTTP ingress and only exposes public selectors with a required preview', () => {
  const html = renderToStaticMarkup(React.createElement(TunnelModal, { ...common, record, report, onPreview: noop }));
  assert.ok(html.includes('xhttp') && html.includes('203.0.113.20:2222'));
  assert.ok(html.includes('127.0.0.1:15443') && html.includes('127.0.0.1:8443'));
  assert.ok(html.includes('&lt;phone&gt;') && html.includes('&lt;gb-exit&gt;'));
  assert.ok(!html.includes('value="direct"') && !html.includes('value="ssh-ultra-gb"'));
  assert.match(html, /<input(?=[^>]*type="checkbox")(?=[^>]*required)[^>]*>/);
  assert.ok(html.includes('Посмотреть план') && html.includes('телефон → Москва'));
});

test('SSH modal refuses stale or absent inbound inventory', () => {
  const stale = { ...report, panels: [{ ...report.panels[0], inbounds: [{ ...inbound, fingerprint: undefined }] }] };
  const html = renderToStaticMarkup(React.createElement(TunnelModal, { ...common, record, report: stale, onPreview: noop }));
  assert.ok(html.includes('обнови обнаружение') && !html.includes('value="1"'));
});

test('SSH plan clearly identifies the remote mutation and restart', () => {
  const html = renderToStaticMarkup(React.createElement(PlanModal, { ...common, record, action: 'tunnel',
    plan: { files: {}, steps: [], remote_dir: '/opt/omsi-nodekit/ultra' }, onReload: noop, onLaunch: noop }));
  assert.ok(html.includes('Изменяет сервер') && html.includes('Xray перезапустится'));
  assert.ok(!html.includes('Сервисы на VPS не изменяются'));
});
