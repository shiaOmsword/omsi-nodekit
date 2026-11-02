import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { DeploymentModal } = compiled('features/nodes/DeploymentModal.js');
const { SubscriptionReport, InboundReport } = compiled('features/nodes/SubscriptionReport.js');
const { PlanModal } = compiled('features/operations/PlanModal.js');
const { parseRoute } = compiled('framework/navigation/router.js');
const noop = () => {};
const record = { id: 'ultra', name: 'Ultra', yaml: `id: ultra
name: Ultra
ssh:
  host: 203.0.113.10
panel:
  installation: managed
  subscription_port: 2097
caddy:
  enabled: true
  domain: sub.example.com
  https_port: 2096
deployment:
  role: ingress
  panel_runtime: docker
  caddy_mode: existing
  caddy_id: docker:abc
  subscription_bind: 172.30.50.1
  install_docker: false
  inbounds:
    - name: first
      port: 8443
      listen: 0.0.0.0
      server_name: example.com
      target_port: 443
      client_email: test-client
` };

test('custom subscription port has an explicit publication warning and safe first-client form', () => {
  const html = renderToStaticMarkup(React.createElement(DeploymentModal, {
    record, report: { panels: [{ installation: 'managed', active: true }], caddy: [{
      id: 'docker:abc', container: 'shared-caddy', installation: 'docker', network_mode: 'bridge',
      published_ports: ['0.0.0.0:443->443/tcp'],
    }] }, busy: false, error: '', onClose: noop, onSave: noop,
  }));
  assert.ok(html.includes('https://sub.example.com:2096/sub/'));
  assert.ok(html.includes('2096:2096/tcp'));
  assert.ok(html.includes('Имя первого клиента'));
  assert.ok(html.includes('value="test-client"'));
  assert.match(html, /name="runtime"[^>]*disabled/);
  for (const [, pattern] of html.matchAll(/pattern="([^"]+)"/g)) assert.doesNotThrow(() => new RegExp(pattern, 'v'));
});

test('configure is a separate mutation with an explicit preview', () => {
  assert.equal(parseRoute('#/nodes/ultra/operations/configure').action, 'configure');
  const html = renderToStaticMarkup(React.createElement(PlanModal, {
    record, action: 'configure', plan: { remote_dir: '/opt/omsi-nodekit/ultra', steps: ['Verify ownership'], files: {} },
    busy: false, error: '', onClose: noop, onReload: noop, onLaunch: noop,
  }));
  assert.ok(html.includes('Изменяет сервер'));
  assert.ok(!html.includes('Сервисы на VPS не изменяются'));
  assert.ok(html.includes('активные VPN-соединения могут прерваться'));
});

test('saved YAML may omit optional deployment defaults', () => {
  const html = renderToStaticMarkup(React.createElement(DeploymentModal, {
    record: { ...record, yaml: 'id: ultra\nname: Ultra\nssh:\n  host: 203.0.113.10\ndeployment:\n  panel_runtime: docker\n' },
    report: null, busy: false, error: '', onClose: noop, onSave: noop,
  }));
  assert.ok(html.includes('Inbound не заданы'));
  assert.match(html, /value="docker" selected=""/);
});

test('subscription report distinguishes failing Caddy hop and external verification scope', () => {
  const html = renderToStaticMarkup(React.createElement(SubscriptionReport, { report: {
    subscription_url_template: 'https://sub.example.com:2096/sub/<subscription-id>',
    subscription_checks: [
      { name: 'upstream', state: 'ok', detail: 'HTTP 200' },
      { name: 'caddy_upstream', state: 'error', detail: 'Firewall timeout' },
    ],
  } }));
  assert.ok(html.includes('Caddy → сервер подписок'));
  assert.ok(html.includes('Ошибка'));
  assert.ok(html.includes('с VPS с проверкой сертификата'));
  assert.ok(html.includes('&lt;subscription-id&gt;'));
});

test('inbound inventory escapes names and does not render private identities from source objects', () => {
  const html = renderToStaticMarkup(React.createElement(InboundReport, { panel: {
    inbounds_readable: true, inbounds: [{ id: 1, remark: '<script>bad</script>', enabled: true,
      protocol: 'vless', listen: '0.0.0.0', port: 8443, network: 'tcp', security: 'reality',
      client_count: 1, privateKey: 'do-not-render-private', clients: [{ email: 'test-client', enabled: true,
        has_subscription: true, subId: 'do-not-render-sub-id', id: 'do-not-render-uuid' }],
    }],
  } }));
  assert.ok(html.includes('0.0.0.0:8443'));
  assert.ok(html.includes('test-client'));
  assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert.ok(!html.includes('do-not-render'));
});

test('Caddy attachment has an explicit mutation preview and a dedicated route', () => {
  assert.equal(parseRoute('#/nodes/ultra/operations/attach_caddy').action, 'attach_caddy');
  const html = renderToStaticMarkup(React.createElement(PlanModal, {
    record, action: 'attach_caddy', plan: { remote_dir: '/opt/omsi-nodekit/ultra', steps: ['Attach Caddy'], files: {} },
    busy: false, error: '', onClose: noop, onReload: noop, onLaunch: noop,
  }));
  assert.ok(html.includes('Подключить Caddy: план'));
  assert.ok(html.includes('Изменяет сервер'));
  assert.ok(html.includes('127.0.0.1:2019'));
  assert.ok(html.includes('активные VPN-соединения могут прерваться'));
  assert.ok(!html.includes('Сервисы на VPS не изменяются'));
});

const { NodePage } = compiled('features/nodes/NodePage.js');

function inboundPage(attachment, caddyMode = 'existing', reportHost = '203.0.113.10') {
  return renderToStaticMarkup(React.createElement(NodePage, {
    route: { page: 'node', id: 'ultra', tab: 'inbounds' },
    workspace: { selected: record, nodes: [{ ...record, state: 'active' }], jobs: [], keys: [],
      config: { ssh: { host: '203.0.113.10', port: 22 }, panel: { installation: 'managed' }, deployment: { caddy_mode: caddyMode } },
    },
    reportJob: { report: { ssh_host: reportHost, ssh_port: 22, caddy_attachment: attachment,
      selected_panel: 'docker:panel', panels: [{ id: 'docker:panel', installation: 'managed', inbounds_readable: true, inbounds: [] }] } },
    navigate: noop, onPlan: noop, onDeployment: noop,
  }));
}

test('XHTTP waits for persisted Caddy attachment and offers the next operation', () => {
  const unattached = inboundPage('required');
  assert.ok(unattached.includes('Сначала подключи его, затем создай XHTTP'));
  assert.match(unattached, /<button[^>]*disabled[^>]*>[^<]*\+ VLESS \/ XHTTP/);
  assert.ok(unattached.includes('Подключить Caddy'));
  const ready = inboundPage('ready');
  assert.doesNotMatch(ready, /<button[^>]*disabled[^>]*>[^<]*\+ VLESS \/ XHTTP/);
  assert.ok(ready.includes('+ VLESS / XHTTP'));
});

test('an old report or another SSH host cannot unlock XHTTP', () => {
  for (const html of [inboundPage(undefined), inboundPage('ready', 'existing', '203.0.113.99')]) {
    assert.match(html, /<button[^>]*disabled[^>]*>[^<]*\+ VLESS \/ XHTTP/);
    assert.ok(html.includes('Обнови обнаружение'));
  }
  assert.ok(inboundPage('required', 'docker').includes('Настроить Caddy'));
});
