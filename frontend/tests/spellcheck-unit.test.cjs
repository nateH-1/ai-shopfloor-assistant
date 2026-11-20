const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function loadSpellcheck() {
  const source = readFileSync(path.join(__dirname, "../src/lib/spellcheck.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const context = { exports: {} };
  vm.runInNewContext(outputText, context);
  return context.exports;
}

function loadChatApi(tabFetch) {
  const source = readFileSync(path.join(__dirname, "../src/lib/chatApi.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const requests = [];
  const context = {
    exports: {},
    process: { env: {} },
    FormData,
    AbortSignal,
    require: (name) => {
      assert.equal(name, "./tabSession");
      return {
        tabFetch: async (url, init) => {
          requests.push({ url, init });
          return tabFetch(url, init);
        },
      };
    },
  };
  vm.runInNewContext(outputText, context);
  return { api: context.exports, requests };
}

const spell = loadSpellcheck();

test("suggestion filter drops wrong first letters", () => {
  const spans = spell.misspelledSpans(
    "ncc",
    () => false,
    () => ["cc", "FCC", "nice", "neck"],
  );
  assert.equal(JSON.stringify(spans[0].suggestions), JSON.stringify(["nice", "neck"]));
});

test("suggestion filter drops length gaps larger than two", () => {
  const spans = spell.misspelledSpans(
    "inal",
    () => false,
    () => ["i", "initial", "into", "ink"],
  );
  assert.equal(JSON.stringify(spans[0].suggestions), JSON.stringify(["into", "ink"]));
});

test("suggestions are capped at five", () => {
  const spans = spell.misspelledSpans(
    "meged",
    () => false,
    () => ["meted", "mewed", "merged", "mended", "melted", "meshed", "minded"],
  );
  assert.equal(spans[0].suggestions.length, 5);
  assert.equal(JSON.stringify(spans[0].suggestions), JSON.stringify([
    "meted", "mewed", "merged", "mended", "melted",
  ]));
});

test("very long nonsense words are underlined without suggestions", () => {
  const word = "prsdhvyudvgdvgdvvedgvvabcdef";
  assert.ok(word.length > 24);
  const spans = spell.misspelledSpans(
    word,
    () => false,
    () => ["should", "not", "appear"],
  );
  assert.equal(spans.length, 1);
  assert.equal(spans[0].start, 0);
  assert.equal(spans[0].end, word.length);
  assert.equal(JSON.stringify(spans[0].suggestions), JSON.stringify([]));
});

test("replaceMisspelling rejects empty and invalid ranges", () => {
  const text = "what is our meged plan";
  assert.equal(spell.replaceMisspelling(text, 12, 17, ""), null);
  assert.equal(spell.replaceMisspelling(text, 12, 12, "merged"), null);
  assert.equal(spell.replaceMisspelling(text, 17, 12, "merged"), null);
  assert.equal(spell.replaceMisspelling(text, -1, 17, "merged"), null);
  assert.equal(spell.replaceMisspelling(text, 12, 99, "merged"), null);
  assert.equal(spell.replaceMisspelling(text, 12.5, 17, "merged"), null);
});

test("findMisspellings returns an empty list when the spelling route is not ok", async () => {
  const { api } = loadChatApi(async () => ({ ok: false, status: 502, json: async () => ({ spans: [{ start: 0, end: 5 }] }) }));
  assert.equal(JSON.stringify(await api.findMisspellings("meged")), JSON.stringify([]));
});

test("findMisspellings drops bad spans and caps suggestions at five", async () => {
  const { api } = loadChatApi(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      spans: [
        {
          start: 0,
          end: 5,
          suggestions: ["merged", " ", 12, "", "meted", "mewed", "mended", "melted", "meshed"],
        },
        { start: "0", end: 3, suggestions: ["nope"] },
        { start: 8, end: 13 },
      ],
    }),
  }));
  assert.equal(JSON.stringify(await api.findMisspellings("meged xx asdfg")), JSON.stringify([
    { start: 0, end: 5, suggestions: ["merged", "meted", "mewed", "mended", "melted"] },
    { start: 8, end: 13, suggestions: [] },
  ]));
});

test("empty text produces no misspelling spans", () => {
  assert.equal(JSON.stringify(spell.misspelledSpans("", () => false)), JSON.stringify([]));
});

test("punctuation stays outside the misspelled span", () => {
  const text = "meged!";
  const spans = spell.misspelledSpans(text, () => false, () => ["merged"]);
  assert.equal(text.slice(spans[0].start, spans[0].end), "meged");
  assert.equal(spans[0].end, 5);
  assert.equal(text[spans[0].end], "!");
});

test("findMisspellings passes AbortSignal through", async () => {
  const controller = new AbortController();
  const { api, requests } = loadChatApi(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ spans: [] }),
  }));
  await api.findMisspellings("meged", controller.signal);
  assert.equal(requests[0].init.signal, controller.signal);
});

test("one-letter words are ignored by misspelledSpans", () => {
  const spans = spell.misspelledSpans("a I x meged", () => false, () => ["merged"]);
  assert.equal(spans.length, 1);
  assert.equal("a I x meged".slice(spans[0].start, spans[0].end), "meged");
});
