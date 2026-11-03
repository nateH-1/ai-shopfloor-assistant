// Route contracts with controlled local-service responses, not real recognition.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { File } = require('node:buffer');

function route(fetch) {
  const exports = {};
  const source = fs.readFileSync(path.join(__dirname, '../src/app/api/transcribe/route.ts'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(code, {
    exports, fetch, File, FormData, AbortSignal, console: { error() {} },
    process: { env: { FLASK_URL: 'http://127.0.0.1:5000' } },
    require(name) {
      if (name === 'next/server') return { NextResponse: { json: (data, init = {}) => ({ data, status: init.status ?? 200 }) } };
      if (name === '@/lib/server/feedbackIdentity') return {
        hasForeignOrigin: req => req.headers.get('origin') !== null && req.headers.get('origin') !== req.nextUrl.origin,
      };
      throw new Error(name);
    },
  });
  return exports.POST;
}

function request(audio, headers = {}) {
  const form = new FormData();
  if (audio !== undefined) form.append('audio', audio);
  return { headers: new Headers(headers), nextUrl: new URL('http://localhost:3000/api/transcribe'),
    formData: async () => form };
}
const audio = () => new File(['recording'], 'recording.webm', { type: 'audio/webm' });

test('uses only local backend without an OpenAI key or authorization header', async () => {
  const calls = [];
  const post = route(async (...args) => { calls.push(args); return { ok: true, json: async () => ({ text: ' Heat treatment. ' }) }; });
  const response = await post(request(audio()));
  assert.equal(response.status, 200);
  assert.equal(response.data.text, 'Heat treatment.');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'http://127.0.0.1:5000/api/transcribe');
  assert.equal(calls[0][1].body.get('audio').name, 'recording.webm');
  assert.equal(calls[0][1].headers, undefined);
  assert.equal(calls[0][1].body.get('model'), null);
  assert.ok(calls[0][1].signal instanceof AbortSignal);
});

test('rejects missing and empty audio before contacting backend', async () => {
  const post = route(() => assert.fail('Should not fetch'));
  assert.equal((await post(request())).status, 400);
  assert.equal((await post(request(new File([], 'empty.webm')))).status, 400);
});

test('rejects oversized request before reading multipart body', async () => {
  const post = route(() => assert.fail('Should not fetch'));
  const req = request(audio(), { 'content-length': String(26 * 1024 * 1024) });
  req.formData = () => assert.fail('Should not read oversized body');
  assert.equal((await post(req)).status, 413);
});

test('rejects a foreign origin without forwarding the recording', async () => {
  const post = route(() => assert.fail('Should not fetch'));
  assert.equal((await post(request(audio(), { origin: 'https://other.example' }))).status, 403);
});

for (const [status, message] of [[503, 'Local speech model is missing.'], [422, 'No speech was detected.'], [429, 'Another recording is being transcribed.']]) {
  test(`preserves local-service ${status} and actionable message`, async () => {
    const post = route(async () => ({ ok: false, status, json: async () => ({ error: message }) }));
    const response = await post(request(audio()));
    assert.equal(response.status, status);
    assert.equal(response.data.error, message);
  });
}

test('unreachable backend returns 502 without trying a cloud fallback', async () => {
  let calls = 0;
  const post = route(async () => { calls++; throw new Error('connection refused'); });
  assert.equal((await post(request(audio()))).status, 502);
  assert.equal(calls, 1);
});

test('empty successful response is not accepted as a transcript', async () => {
  const post = route(async () => ({ ok: true, json: async () => ({ text: ' ' }) }));
  assert.equal((await post(request(audio()))).status, 422);
});
