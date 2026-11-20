const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const { NextRequest } = require("next/server");

const OWNER = "291554e9-2d0a-4665-af69-a19ff2bd7f59";
const COOKIE = "manufacturing_feedback_browser";

function loadIdentity(env = {}) {
  const source = readFileSync(path.join(__dirname, "../src/lib/server/feedbackIdentity.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const context = {
    exports: {},
    process: { env: { ...env } },
    require(name) {
      if (name === "next/server") return require("next/server");
      if (name === "node:crypto") return require("node:crypto");
      return require(name);
    },
  };
  vm.runInNewContext(outputText, context);
  return context.exports;
}

function request(headers = {}) {
  return new NextRequest("http://localhost:3000/api/feedback/x", { headers });
}

test("valid feedback cookie owner is accepted", () => {
  const { feedbackOwner } = loadIdentity();
  const owner = feedbackOwner(request({ cookie: `${COOKIE}=${OWNER}` }));
  assert.equal(owner, OWNER);
});

test("invalid or missing feedback cookie owners are ignored", () => {
  const { feedbackOwner } = loadIdentity();
  assert.equal(feedbackOwner(request({ cookie: `${COOKIE}=not-a-uuid` })), undefined);
  assert.equal(feedbackOwner(request()), undefined);
});

test("foreign origin is blocked", () => {
  const { hasForeignOrigin } = loadIdentity();
  const req = new NextRequest("http://localhost:3000/api/chat", {
    headers: { origin: "https://evil.example" },
  });
  assert.equal(hasForeignOrigin(req), true);
});

test("same origin and allowed APP_ORIGIN are accepted", () => {
  const { hasForeignOrigin } = loadIdentity({ APP_ORIGIN: "https://shopfloor.example" });
  const same = new NextRequest("http://localhost:3000/api/chat", {
    headers: { origin: "http://localhost:3000" },
  });
  const allowed = new NextRequest("http://localhost:3000/api/chat", {
    headers: { origin: "https://shopfloor.example" },
  });
  const none = new NextRequest("http://localhost:3000/api/chat");
  assert.equal(hasForeignOrigin(same), false);
  assert.equal(hasForeignOrigin(allowed), false);
  assert.equal(hasForeignOrigin(none), false);
});
