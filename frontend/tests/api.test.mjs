import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { api, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

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
    assert.equal(options.headers['X-Nodekit-Request'], '1');
    assert.equal(options.headers['Content-Type'], 'application/octet-stream');
    return new Response(JSON.stringify({ ok: true, data: { id: 'backup' }, error: null, meta }), { status: 201 });
  }, async () => {
    assert.deepEqual(await api('/backups', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: new Uint8Array([1, 2]) }), { id: 'backup' });
  });
});
