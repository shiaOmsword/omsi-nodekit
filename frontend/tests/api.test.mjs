import assert from 'node:assert/strict';
import test from 'node:test';
import { compiled } from './helpers/compiled.mjs';

const { api, ApiError, ErrorCode } = compiled('api.js');

async function withFetch(fake, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try { await run(); } finally { globalThis.fetch = original; }
}
const meta = { request_id: 'request-123' };

test('unwraps successful envelopes for existing React callers', async () => {
  await withFetch(async () => new Response(JSON.stringify({ ok: true, data: [{ id: 'node' }], error: null, meta })), async () => {
    assert.deepEqual(await api('/nodes'), [{ id: 'node' }]);
  });
});

test('preserves structured error fields, status and request ID', async () => {
  const error = { code: 'validation_error', message: 'Entity validation failed', details: [{ field: 'ssh.host', code: 'pattern' }] };
  await withFetch(async () => new Response(JSON.stringify({ ok: false, data: null, error, meta }), { status: 422 }), async () => {
    await assert.rejects(api('/config/validate'), value => {
      assert(value instanceof ApiError);
      assert.equal(value.code, 'validation_error');
      assert.equal(value.status, 422);
      assert.equal(value.requestId, 'request-123');
      assert.equal(value.details[0].field, 'ssh.host');
      assert.match(value.message, /ssh.host/);
      return true;
    });
  });
});

test('rejects an old or malformed JSON contract', async () => {
  await withFetch(async () => new Response(JSON.stringify({ detail: 'legacy response' })), async () => {
    await assert.rejects(api('/nodes'), error => error.code === 'invalid_response');
  });
});

test('handles a non-JSON upstream error', async () => {
  await withFetch(async () => new Response('<html>Bad gateway</html>', { status: 502 }), async () => {
    await assert.rejects(api('/nodes'), error => error instanceof ApiError && error.status === 502);
  });
});

test('keeps binary upload headers and the local request marker', async () => {
  await withFetch(async (path, options) => {
    assert.equal(path, '/api/backups');
    assert.equal(options.headers.get('X-Nodekit-Request'), '1');
    assert.equal(options.headers.get('Content-Type'), 'application/octet-stream');
    return new Response(JSON.stringify({ ok: true, data: { id: 'backup' }, error: null, meta }), { status: 201 });
  }, async () => {
    assert.deepEqual(await api('/backups', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: new Uint8Array([1, 2]) }), { id: 'backup' });
  });
});


test('network failures have a stable client code and no raw exception leakage', async () => {
  await withFetch(async () => { throw new TypeError('private proxy details'); }, async () => {
    await assert.rejects(api('/nodes'), error => error instanceof ApiError && error.code === ErrorCode.NetworkError && !error.message.includes('private proxy'));
  });
});

test('malformed error details are rejected before reaching the UI', async () => {
  await withFetch(async () => new Response(JSON.stringify({ok:false,data:null,error:{code:'validation_error',message:'bad',details:'not-an-array'},meta}), {status:422}), async () => {
    await assert.rejects(api('/nodes'), error => error.code === ErrorCode.InvalidResponse);
  });
});

test('request cancellation is preserved', async () => {
  const abort = new DOMException('aborted', 'AbortError');
  await withFetch(async () => { throw abort; }, async () => {
    await assert.rejects(api('/nodes'), error => error === abort);
  });
});
