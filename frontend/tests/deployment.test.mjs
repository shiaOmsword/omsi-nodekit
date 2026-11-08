import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { DeploymentModal } = compiled('features/nodes/DeploymentModal.js');
const { DiscoveryModal } = compiled('features/nodes/DiscoveryModal.js');
const { defaultTarget } = compiled('app/config.js');
const { InstallationReportView } = compiled('features/nodes/InstallationReportView.js');
const { messages } = compiled('framework/messages/index.js');
const noop = () => {};
const inventory = {
  observed_at: '2026-10-30T15:00:00Z',
  panels: [],
  caddy: [],
  capabilities: {},
  warnings: [],
  selected_panel: null,
};
const record = {
  id: 'exit',
  name: 'Exit',
  yaml: 'id: exit\nname: Exit\nssh:\n  host: 203.0.113.10\n',
};

test('missing panel is a normal summary without ambiguous-selection error', () => {
  const html = renderToStaticMarkup(
    React.createElement(InstallationReportView, { report: inventory, node: 'exit' }),
  );
  assert.ok(html.includes('Не обнаружена'));
  assert.ok(!html.includes(messages.report.notSelected));
  assert.ok(!html.includes('role="alert"'));
});

test('an unselected existing panel still requires explicit selection', () => {
  const report = {
    ...inventory,
    panels: [
      {
        id: 'native:x-ui',
        installation: 'native',
        active: true,
        settings: {},
        defaulted_settings: [],
        certificates: [],
        warnings: [],
      },
    ],
  };
  const html = renderToStaticMarkup(
    React.createElement(InstallationReportView, { report, node: 'exit' }),
  );
  assert.ok(html.includes(messages.report.notSelected));
});

test('deployment modal recommends Docker and Caddy without inventing REALITY identity', () => {
  const target = defaultTarget();
  assert.equal(target.panel_runtime, 'docker');
  assert.equal(target.caddy_mode, 'docker');
  assert.deepEqual(target.inbounds, []);
  const html = renderToStaticMarkup(
    React.createElement(DeploymentModal, {
      record,
      report: null,
      busy: false,
      error: '',
      onClose: noop,
      onSave: noop,
    }),
  );
  assert.match(html, /value="docker" selected=""/);
  assert.ok(html.includes('Параметры установки'));
  assert.ok(html.includes('Сохранить параметры'));
  assert.ok(html.includes('Inbound не заданы'));
  assert.ok(!html.includes('privateKey'));
});

test('discovery modal requires an explicit optional Caddy choice and disables busy form', () => {
  const report = { ...inventory, caddy: [{ id: 'docker:abc', container: 'shared-caddy' }] };
  const html = renderToStaticMarkup(
    React.createElement(DiscoveryModal, {
      record,
      report,
      busy: true,
      error: '',
      onClose: noop,
      onSave: noop,
    }),
  );
  assert.ok(html.includes('shared-caddy'));
  assert.ok(html.includes('Не подключать'));
  assert.ok(html.includes('<fieldset disabled=""'));
  assert.ok(html.includes('Применить и сохранить'));
});

test('incomplete inventory is not presented as proof that no panel is installed', () => {
  const html = renderToStaticMarkup(
    React.createElement(InstallationReportView, {
      report: { ...inventory, warnings: ['Docker inspection failed'] },
      node: 'exit',
    }),
  );
  assert.ok(html.includes('Не удалось определить'));
  assert.ok(!html.includes('Можно подготовить новую установку'));
});
