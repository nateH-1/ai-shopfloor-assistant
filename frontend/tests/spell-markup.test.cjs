const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "../src/lib/spellMarkup.ts"), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
});
const context = { exports: {} };
vm.runInNewContext(outputText, context);

test("spell pieces keep spaces and mark only the reported words", () => {
  const text = "leeter nt fodn";
  const pieces = context.exports.spellPieces(text, [
    { start: 0, end: 6 },
    { start: 7, end: 9 },
    { start: 10, end: 14 },
  ]);
  assert.equal(JSON.stringify(pieces), JSON.stringify([
    { text: "leeter", misspelled: true },
    { text: " ", misspelled: false },
    { text: "nt", misspelled: true },
    { text: " ", misspelled: false },
    { text: "fodn", misspelled: true },
  ]));
});

test("overlapping or backwards ranges do not cover the same letters twice", () => {
  const pieces = context.exports.spellPieces("materil", [
    { start: 4, end: 2 },
    { start: 0, end: 7 },
    { start: 3, end: 7 },
  ]);
  assert.equal(JSON.stringify(pieces), JSON.stringify([
    { text: "materil", misspelled: true },
  ]));
});

test("highlight markup keeps every character, including symbols", () => {
  const text = "a <b> & meged";
  const html = context.exports.highlightedHtml(text, [{ start: 8, end: 13 }]);
  assert.equal(html, "a &lt;b&gt; &amp; <span class=\"misspelled-word\" data-start=\"8\" data-end=\"13\">meged</span>");
  assert.equal(context.exports.spellPieces(text, [{ start: 8, end: 13 }]).map((piece) => piece.text).join(""), text);
});

test("empty draft HTML stays empty so the placeholder can show", () => {
  assert.equal(context.exports.highlightedHtml("", [{ start: 0, end: 1 }]), "");
});

test("invalid and unsorted spans still render safely", () => {
  assert.equal(
    context.exports.highlightedHtml("materials", [
      { start: -1, end: 3 },
      { start: 2, end: 2 },
      { start: 9, end: 12 },
    ]),
    "materials",
  );
  assert.equal(
    context.exports.highlightedHtml("aa bb", [
      { start: 3, end: 5 },
      { start: 0, end: 2 },
    ]),
    "<span class=\"misspelled-word\" data-start=\"0\" data-end=\"2\">aa</span> <span class=\"misspelled-word\" data-start=\"3\" data-end=\"5\">bb</span>",
  );
});
