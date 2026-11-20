const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function loadTheme(globals = {}) {
  const source = readFileSync(path.join(__dirname, "../src/lib/theme.ts"), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const context = { exports: {}, ...globals };
  vm.runInNewContext(outputText, context);
  return context.exports;
}

test("parseTheme accepts light, dark, and red", () => {
  const { parseTheme } = loadTheme();
  assert.equal(parseTheme("light"), "light");
  assert.equal(parseTheme("dark"), "dark");
  assert.equal(parseTheme("red"), "red");
});

test("parseTheme rejects unknown values", () => {
  const { parseTheme } = loadTheme();
  assert.equal(parseTheme(null), null);
  assert.equal(parseTheme(""), null);
  assert.equal(parseTheme("blue"), null);
  assert.equal(parseTheme("DARK"), null);
});

test("applyTheme toggles dark and red classes on the document root", () => {
  const classList = new Set();
  const { applyTheme } = loadTheme({
    document: {
      documentElement: {
        classList: {
          toggle(name, enabled) {
            if (enabled) classList.add(name);
            else classList.delete(name);
          },
        },
      },
    },
  });

  applyTheme("dark");
  assert.equal(JSON.stringify([...classList].sort()), JSON.stringify(["dark"]));

  applyTheme("red");
  assert.equal(JSON.stringify([...classList].sort()), JSON.stringify(["red"]));

  applyTheme("light");
  assert.equal(JSON.stringify([...classList].sort()), JSON.stringify([]));
});

test("readStoredTheme reads a saved theme", () => {
  const { readStoredTheme } = loadTheme({
    window: {
      localStorage: {
        getItem(key) {
          assert.equal(key, "shopfloor.theme");
          return "red";
        },
      },
    },
  });
  assert.equal(readStoredTheme(), "red");
});

test("blocked localStorage returns null from readStoredTheme", () => {
  const { readStoredTheme } = loadTheme({
    window: {
      localStorage: {
        getItem() {
          throw new Error("blocked");
        },
      },
    },
  });
  assert.equal(readStoredTheme(), null);
});
