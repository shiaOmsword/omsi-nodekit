import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { DeploymentSettings, defaultTarget } = compiled('features/nodes/DeploymentSettings.js');
const { DiscoverySuggestions } = compiled('features/nodes/DiscoverySuggestions.js');
const { InstallationReportView } = compiled('features/nodes/InstallationReportView.js');
const { messages } = compiled('framework/messages/index.js');
const { deploymentMessages: t } = compiled('features/nodes/deploymentMessages.js');
const noop = () => {};
const inventory = { observed_at: '2026-10-30T15:00:00Z', panels: [], caddy: [], capabilities: {}, warnings: [], selected_panel: null };

test('missing panel is an installation scenario without an ambiguous-selection error', () => {
  const html = renderToStaticMarkup(React.createElement(InstallationReportView, { report: inventory, node: 'exit' }));
  assert.ok(html.includes(t.noPanel));
  assert.ok(!html.includes(messages.report.notSelected));
  assert.ok(!html.includes('role="alert"'));
});

test('ambiguous existing panels still require selection', () => {
  const report = { ...inventory, panels: [{ id: 'native:x-ui', installation: 'native', active: true, settings: {}, defaulted_settings: [], certificates: [], warnings: [] }] };
  const html = renderToStaticMarkup(React.createElement(InstallationReportView, { report, node: 'exit' }));
  assert.ok(html.includes(messages.report.notSelected));
});

test('exit defaults use native 3x-ui without Caddy or invented REALITY identities', () => {
  const target = defaultTarget();
  assert.equal(target.role, 'exit');
  assert.equal(target.panel_runtime, 'native');
  assert.equal(target.caddy_mode, 'none');
  assert.deepEqual(target.inbounds, []);
  const html = renderToStaticMarkup(React.createElement(DeploymentSettings, { draft: { deployment: target }, report: null, busy: false, onApply: noop }));
  assert.match(html, /value="native" selected=""/);
  assert.ok(html.includes(t.inboundHint));
  assert.ok(html.includes('type="submit"'));
});

test('discovery suggestions keep shared Caddy selection optional and stale reports disabled', () => {
  const report = { ...inventory, caddy: [{ id: 'docker:abc', container: 'shared-caddy' }] };
  const html = renderToStaticMarkup(React.createElement(DiscoverySuggestions, { report, disabled: true, onApply: noop }));
  assert.ok(html.includes('shared-caddy'));
  assert.ok(html.includes(t.noCaddy));
  assert.ok(html.includes('disabled=""'));
});
