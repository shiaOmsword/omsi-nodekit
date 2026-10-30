import test from 'node:test';
import assert from 'node:assert/strict';
import { compiled } from './helpers/compiled.mjs';

const { ApiError } = compiled('framework/api/errors.js');
const { getNodeErrorMessage } = compiled('features/nodes/configErrors.js');

function invalid(code) {
  return new ApiError('Entity validation failed', 'validation_error', 422,
    [{ field: 'ssh.sudo_password', code }]);
}

test('old backend reports actionable extra_forbidden error', () => {
  assert.match(getNodeErrorMessage(invalid('extra_forbidden')), /backend.*dev/);
});

test('unquoted numeric password reports YAML string requirement', () => {
  assert.match(getNodeErrorMessage(invalid('string_type')), /строкой/);
});

test('invalid password format has a safe readable message', () => {
  assert.match(getNodeErrorMessage(invalid('value_error')), /4096/);
});

test('unrelated errors preserve the original message', () => {
  assert.equal(getNodeErrorMessage(new ApiError('Cannot connect', 'network_error', 0)), 'Cannot connect');
});
