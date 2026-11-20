const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function loadRoute({ foreign = false, check } = {}) {
  const source = readFileSync(path.join(__dirname, "../src/app/api/chat/spelling/route.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const context = {
    exports: {},
    console: { error() {} },
    require(name) {
      if (name === "next/server") {
        return {
          NextResponse: {
            json: (data, init = {}) => ({ data, status: init.status ?? 200 }),
          },
        };
      }
      if (name === "dictionary-en") return { default: { aff: new Uint8Array(), dic: new Uint8Array() } };
      if (name === "nspell") {
        return {
          default: () => ({
            add() {},
            correct: () => true,
            suggest: () => [],
          }),
        };
      }
      if (name === "@/lib/server/feedbackIdentity") {
        return { hasForeignOrigin: () => foreign };
      }
      if (name === "@/lib/spellcheck") {
        return {
          misspelledSpans: (text, isWord, suggest) => {
            if (typeof check === "function") return check(text, isWord, suggest);
            return text
              ? [{ start: 0, end: Math.min(5, text.length), suggestions: ["merged"] }]
              : [];
          },
        };
      }
      throw new Error(`Unexpected require: ${name}`);
    },
  };
  vm.runInNewContext(outputText, context);
  return context.exports.POST;
}

function request(body, headers = {}) {
  return {
    headers: new Headers(headers),
    nextUrl: new URL("http://localhost:3000/api/chat/spelling"),
    json: async () => body,
  };
}

test("spelling route returns spans for draft text", async () => {
  const post = loadRoute();
  const response = await post(request({ text: "meged plan" }));
  assert.equal(response.status, 200);
  assert.equal(JSON.stringify(response.data.spans), JSON.stringify([
    { start: 0, end: 5, suggestions: ["merged"] },
  ]));
});

test("spelling route blocks a foreign origin", async () => {
  const post = loadRoute({ foreign: true });
  const response = await post(request({ text: "meged" }, { origin: "https://evil.example" }));
  assert.equal(response.status, 403);
  assert.equal(response.data.error, "Cross-site chat requests are not allowed.");
});

test("spelling route returns empty spans for bad bodies or checker failures", async () => {
  const badBody = loadRoute();
  assert.equal(JSON.stringify((await badBody(request({ text: 12 }))).data.spans), JSON.stringify([]));
  assert.equal(JSON.stringify((await badBody(request({}))).data.spans), JSON.stringify([]));

  const failing = loadRoute({
    check() {
      throw new Error("dictionary failed");
    },
  });
  const response = await failing(request({ text: "meged" }));
  assert.equal(response.status, 502);
  assert.equal(JSON.stringify(response.data.spans), JSON.stringify([]));
});
