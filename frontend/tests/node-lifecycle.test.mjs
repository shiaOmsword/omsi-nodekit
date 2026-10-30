import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { NodeLifecycle } = compiled('features/nodes/NodeLifecycle.js');
const noop = () => {};
const selected = { id: 'test-node', name: 'Node', revision: 'sha', yaml: 'id: test-node' };

function render(state) {
  return renderToStaticMarkup(React.createElement(NodeLifecycle, {
    selected: { ...selected, state }, busy: false, onState: noop, onDelete: noop,
  }));
}

test('active node offers hide archive and local delete', () => {
  const html = render('active');
  assert.match(html, /Скрыть/);
  assert.match(html, /В архив/);
  assert.match(html, /Удалить из Nodekit/);
});

test('hidden node can be shown or archived', () => {
  const html = render('hidden');
  assert.match(html, /Показать/);
  assert.match(html, /В архив/);
  assert.doesNotMatch(html, />Скрыть</);
});

test('archived node can be restored', () => {
  const html = render('archived');
  assert.match(html, /Вернуть из архива/);
  assert.doesNotMatch(html, />Скрыть</);
});

test('new node without an id does not offer delete', () => {
  assert.equal(renderToStaticMarkup(React.createElement(NodeLifecycle, {
    selected: null, busy: false, onState: noop, onDelete: noop,
  })), '');
});
