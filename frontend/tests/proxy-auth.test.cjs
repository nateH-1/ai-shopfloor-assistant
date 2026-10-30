const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const { NextRequest } = require("next/server");

const TAB_ID = "77a30f79-ab40-4da4-9418-d719ff1b2e0b";
const OWNER = "291554e9-2d0a-4665-af69-a19ff2bd7f59";
const COOKIE = `session=signed-browser-credential; manufacturing_feedback_browser=${OWNER}`;

function loadSource(filename, fetch) {
  const source = readFileSync(path.join(__dirname, "../src", filename), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const context = {
    exports: {}, process, console, Headers, Buffer, AbortSignal, fetch,
    require(name) {
      return name.startsWith("@/") ? loadSource(`${name.slice(2)}.ts`, fetch) : require(name);
    },
  };
  vm.runInNewContext(outputText, context);
  return context.exports;
}

function request(url, options = {}) {
  return new NextRequest(`http://localhost:3000${url}`, {
    ...options,
    headers: {
      Cookie: COOKIE,
      "X-Tab-ID": TAB_ID,
      "X-User-ID": "untrusted-account",
      "X-Feedback-Owner": "untrusted-owner",
      ...options.headers,
    },
  });
}

test("document list, upload, and delete proxies preserve tab authentication", async () => {
  const form = new FormData();
  form.set("file", new Blob(["sample document"]), "manual.txt");
  const cases = [
    ["app/api/documents/route.ts", "GET", request("/api/documents")],
    ["app/api/documents/upload/route.ts", "POST", request("/api/documents/upload", { method: "POST", body: form })],
    ["app/api/documents/[filename]/route.ts", "DELETE", request("/api/documents/manual.txt", { method: "DELETE" })],
  ];
  for (const [filename, method, req] of cases) {
    let forwarded = false;
    const route = loadSource(filename, async (_url, options) => {
      forwarded = true;
      assert.equal(options.headers.get("cookie"), COOKIE);
      assert.equal(options.headers.get("x-tab-id"), TAB_ID);
      assert.equal(options.headers.has("x-user-id"), false);
      assert.equal(options.headers.has("content-type"), false, "fetch must generate the multipart boundary");
      assert.equal(options.cache, "no-store");
      if (method === "POST") assert.equal(await options.body.get("file").text(), "sample document");
      return Response.json({ success: true });
    });
    const response = await route[method](req, { params: Promise.resolve({ filename: "manual.txt" }) });
    assert.equal(forwarded, true, filename);
    assert.equal(response.status, 200, filename);
    assert.equal(response.headers.get("cache-control"), "no-store", filename);
  }
});

test("chat and feedback forward tab auth while deriving feedback ownership from its cookie", async () => {
  const messageId = "d0ab93eb-bea8-4243-b5db-c929597ba359";
  for (const [filename, method, url, body] of [
    ["app/api/chat/route.ts", "POST", "/api/chat", JSON.stringify({ message: "How does this work?" })],
    ["app/api/feedback/[messageId]/route.ts", "GET", `/api/feedback/${messageId}`, undefined],
  ]) {
    let forwarded = false;
    const route = loadSource(filename, async (_url, options) => {
      forwarded = true;
      assert.equal(options.headers.get("cookie"), COOKIE);
      assert.equal(options.headers.get("x-tab-id"), TAB_ID);
      assert.equal(options.headers.get("x-feedback-owner"), OWNER);
      assert.equal(options.headers.get("content-type"), "application/json");
      assert.equal(options.headers.has("x-user-id"), false);
      assert.equal(options.cache, "no-store");
      return Response.json({ reply: "Test", feedback: null });
    });
    const response = await route[method](request(url, {
      method, body, headers: { "Content-Type": "application/json" },
    }), { params: Promise.resolve({ messageId }) });
    assert.equal(forwarded, true, filename);
    assert.equal(response.status, 200, filename);
    assert.equal(response.headers.get("cache-control"), "no-store", filename);
  }
});

test("document proxy preserves a missing-session rejection", async () => {
  const route = loadSource("app/api/documents/route.ts", async (_url, options) => {
    assert.equal(options.headers.has("cookie"), false);
    assert.equal(options.headers.has("x-tab-id"), false);
    return Response.json({ error: "Please log in." }, { status: 401 });
  });
  const response = await route.GET(new NextRequest("http://localhost:3000/api/documents"));
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { error: "Please log in." });
});
