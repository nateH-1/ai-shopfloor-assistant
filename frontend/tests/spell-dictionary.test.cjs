const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "../src/lib/spellcheck.ts"), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const context = { exports: {} };
vm.runInNewContext(outputText, context);

test("an English dictionary underlines typos and nonsense, not real words", async () => {
  const { default: dictionary } = await import("dictionary-en");
  const { default: nspell } = await import("nspell");
  const spell = nspell(dictionary);
  spell.add("Kuldeep");
  const text = "what is our meged archteure plan asdfgh materials Kuldeep";
  const marked = context.exports.misspelledSpans(text, (word) => spell.correct(word))
    .map((span) => text.slice(span.start, span.end));
  assert.equal(JSON.stringify(marked), JSON.stringify(["meged", "archteure", "asdfgh"]));
  const spans = context.exports.misspelledSpans(
    text,
    (word) => spell.correct(word),
    (word) => spell.suggest(word),
  );
  const meged = spans.find((span) => text.slice(span.start, span.end) === "meged");
  assert.equal(JSON.parse(JSON.stringify(meged.suggestions)).includes("merged"), true);
  const fixed = context.exports.replaceMisspelling(text, meged.start, meged.end, "merged");
  assert.equal(fixed.text, "what is our merged archteure plan asdfgh materials Kuldeep");
  assert.equal(fixed.caret, "what is our ".length + "merged".length);
});
