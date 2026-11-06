import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';

// Compile the same TS module used by the browser; no DOM runtime is needed.
const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const js = stripTypeScriptTypes(source, { mode: 'strip' });
const { api, setToken, downloadText } = await import(
  `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
);
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

test('Python download preserves source text, filename and media type', async () => {
  const originalDocument = globalThis.document;
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  let blob,
    clicked = false,
    revoked;
  const anchor = {
    click: () => {
      clicked = true;
    },
  };
  globalThis.document = { createElement: () => anchor };
  URL.createObjectURL = (value) => {
    blob = value;
    return 'blob:python';
  };
  URL.revokeObjectURL = (value) => {
    revoked = value;
  };
  try {
    const script = '# 中文\npattern = r"1[0-9]{10}"\n';
    downloadText(script, 'exp.py', 'text/x-python;charset=utf-8');
    assert.equal(await blob.text(), script);
    assert.equal(blob.type, 'text/x-python;charset=utf-8');
    assert.equal(anchor.download, 'exp.py');
    assert.equal(clicked, true);
    assert.equal(revoked, 'blob:python');
  } finally {
    globalThis.document = originalDocument;
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  }
});

test('a token rejection before execution refreshes the session and retries once', async () => {
  const original = globalThis.fetch,
    calls = [];
  setToken('old');
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (calls.length === 1) return json({ error: '会话已变化，请刷新页面后重试' }, 403);
    if (calls.length === 2) return json({ token: 'new' });
    return json({ ok: true });
  };
  try {
    assert.deepEqual(await api('/api/projects', 'POST', { name: 'demo' }), { ok: true });
    assert.deepEqual(
      calls.map((call) => call.url),
      ['/api/projects', '/api/bootstrap', '/api/projects'],
    );
    assert.equal(calls[0].init.headers['X-Workspace-Token'], 'old');
    assert.equal(calls[2].init.headers['X-Workspace-Token'], 'new');
    assert.equal(calls[0].init.body, calls[2].init.body);
  } finally {
    globalThis.fetch = original;
  }
});

test('other forbidden responses never cause a write retry', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ error: '不接受跨站写入请求' }, 403);
  };
  try {
    await assert.rejects(api('/api/projects', 'POST', {}), /跨站/);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test('a second token failure terminates instead of repeatedly executing requests', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (url) => {
    calls++;
    return url === '/api/bootstrap'
      ? json({ token: 'new' })
      : json({ error: '会话已变化，请刷新页面后重试' }, 403);
  };
  try {
    await assert.rejects(api('/api/projects', 'POST', {}), /会话/);
    assert.equal(calls, 3);
  } finally {
    globalThis.fetch = original;
  }
});
