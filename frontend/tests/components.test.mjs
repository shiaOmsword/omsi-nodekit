import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { Button, IconButton, Alert, CardHeader } = compiled('framework/components/index.js');
const { messages, formatMessage, statusLabel } = compiled('framework/messages/index.js');
const render = (Component, props, children) => renderToStaticMarkup(React.createElement(Component, props, children));

test('loading buttons cannot submit or launch a second operation', () => {
  const html = render(Button, { loading: true, variant: 'primary' }, 'Run');
  assert.match(html, /type="button"/);
  assert.match(html, /disabled=""/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /Run/);
});

test('icon buttons and notifications provide accessible labels and roles', () => {
  assert.match(render(IconButton, { label: 'Close' }, '×'), /aria-label="Close"/);
  assert.match(render(Alert, { tone: 'error', onClose: () => {} }, 'Failure'), /role="alert"/);
  assert.match(render(Alert, { tone: 'success' }, 'Done'), /role="status"/);
});

test('card content is escaped and remains semantic', () => {
  const html = render(CardHeader, { title: '<script>unsafe</script>', subtitle: 'Node details' });
  assert.match(html, /<h2>&lt;script&gt;/);
  assert(!html.includes('<script>'));
  assert.match(html, /Node details/);
});

test('message formatting validates parameters and handles unknown statuses', () => {
  assert.equal(formatMessage(messages.ui.launch, { action: 'проверку' }), 'Запустить проверку');
  assert.throws(() => formatMessage(messages.ui.launch, {}), /message_parameters_mismatch/);
  assert.equal(statusLabel('new-future-status'), messages.status.unknown);
});
