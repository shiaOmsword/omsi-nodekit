import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { compiled } from './helpers/compiled.mjs';

const { NodeManagementModal } = compiled('features/nodes/NodeManagementModal.js');
const noop = () => {};
function render(state, busy = false) {
  return renderToStaticMarkup(
    React.createElement(NodeManagementModal, {
      node: { id: 'test', name: 'Test', state },
      busy,
      error: '',
      onClose: noop,
      onState: noop,
      onDelete: noop,
    }),
  );
}
test('active node management offers local hide archive and delete in one modal', () => {
  const html = render('active');
  for (const text of [
    'Скрыть из активного списка',
    'Переместить в архив',
    'Удалить из Nodekit',
    'Сервисы на VPS продолжают работать',
  ])
    assert.ok(html.includes(text));
  assert.match(html, /<dialog/);
});
test('hidden nodes can be shown again', () => {
  assert.ok(render('hidden').includes('Показать ноду'));
});
test('archived nodes can be restored and cannot be archived twice', () => {
  const html = render('archived');
  assert.ok(html.includes('Вернуть из архива'));
  assert.ok(!html.includes('Переместить в архив'));
});
test('busy management cannot submit another mutation', () => {
  const html = render('active', true);
  assert.ok(html.includes('disabled=""'));
});
