const assert = require("node:assert/strict");
const { existsSync, readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const ts = require("typescript");

const chrome = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].find((candidate) => candidate && existsSync(candidate));

function transpile(filename, exportName) {
  const source = readFileSync(path.join(__dirname, "../src/lib", filename), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  return outputText.replace(/\bexports\b/g, exportName);
}

const SENTENCE = "nathan aynalem haiel cwbcwc cok cso tell me what the prsdhvyudvgdvgdvvedgvv nathan aynaeelem haile olem is";

test("caret stays with the visible character while highlights refresh", { skip: !chrome, timeout: 60000 }, async () => {
  const puppeteer = require("puppeteer-core");
  const browser = await puppeteer.launch({
    executablePath: chrome,
    headless: true,
    args: ["--font-render-hinting=none"],
  });
  try {
    const page = await browser.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    await page.setContent(`<!doctype html>
      <style>
        .box { width: 240px; font: 14px/1.625 Arial, sans-serif; white-space: pre-wrap; overflow-wrap: break-word; }
        .field { display: grid; width: 240px; }
        .field > * { grid-area: 1 / 1; }
        textarea { width: 100%; height: 100%; margin: 0; padding: 0; border: 0; resize: none; overflow: hidden;
          color: transparent; caret-color: black; background: transparent; font: inherit;
          white-space: pre-wrap; overflow-wrap: break-word; }
        .misspelled-word { background-image: linear-gradient(#dc2626, #dc2626); background-repeat: no-repeat;
          background-size: 100% 2px; background-position: left bottom; }
      </style>
      <div id="editor" class="box" contenteditable="true" spellcheck="false"></div>
      <div class="field">
        <div id="back" class="box"></div>
        <textarea id="area" spellcheck="false"></textarea>
      </div>
      <script>
        const markupExports = {};
        const caretExports = {};
        ${transpile("spellMarkup.ts", "markupExports")}
        ${transpile("editorCaret.ts", "caretExports")}
        window.highlightedHtml = markupExports.highlightedHtml;
        window.selectionOffsets = caretExports.selectionOffsets;
        window.setSelectionOffsets = caretExports.setSelectionOffsets;
      </script>`);

    const loaded = await page.evaluate(() => ({
      highlightedHtml: typeof window.highlightedHtml,
      setSelectionOffsets: typeof window.setSelectionOffsets,
    }));
    assert.equal(loaded.setSelectionOffsets, "function", pageErrors.join("\n") || JSON.stringify(loaded));

    const oldLayers = await page.evaluate((sentence) => {
      const back = document.getElementById("back");
      const area = document.getElementById("area");
      back.innerHTML = window.highlightedHtml(sentence, [{ start: 46, end: 70 }]);
      area.value = sentence;
      area.focus();
      area.setSelectionRange(sentence.length, sentence.length);
      const marker = document.createElement("div");
      const style = getComputedStyle(area);
      marker.style.cssText = `position:absolute;visibility:hidden;white-space:pre-wrap;overflow-wrap:break-word;width:${area.clientWidth}px;font:${style.font};line-height:${style.lineHeight};`;
      marker.textContent = sentence;
      document.body.appendChild(marker);
      const caretRange = document.createRange();
      caretRange.selectNodeContents(marker);
      caretRange.collapse(false);
      const caret = caretRange.getBoundingClientRect();
      const last = back.querySelector(".misspelled-word").getBoundingClientRect();
      marker.remove();
      return { caretTop: caret.top, wordTop: last.top, caretLeft: caret.left, wordLeft: last.left };
    }, SENTENCE);

    await page.focus("#editor");
    await page.evaluate((sentence) => {
      const editor = document.getElementById("editor");
      const refresh = () => {
        const offsets = window.selectionOffsets(editor) ?? { start: editor.textContent.length, end: editor.textContent.length };
        const text = editor.textContent ?? "";
        const spans = [];
        for (const match of text.matchAll(/[A-Za-z]{6,}/g)) spans.push({ start: match.index, end: match.index + match[0].length });
        editor.innerHTML = window.highlightedHtml(text, spans);
        window.setSelectionOffsets(editor, offsets.start, offsets.end);
      };
      editor.addEventListener("input", refresh);
      editor.textContent = sentence;
      editor.focus();
      window.setSelectionOffsets(editor, sentence.length, sentence.length);
      refresh();
    }, SENTENCE);

    const beforeDelete = await page.evaluate(() => {
      const editor = document.getElementById("editor");
      const text = editor.textContent ?? "";
      const offsets = window.selectionOffsets(editor);
      const caretRange = getSelection().getRangeAt(0).cloneRange();
      caretRange.collapse(false);
      const caret = caretRange.getClientRects()[0] || caretRange.getBoundingClientRect();
      window.setSelectionOffsets(editor, text.length - 1, text.length);
      const last = getSelection().getRangeAt(0).getBoundingClientRect();
      window.setSelectionOffsets(editor, text.length, text.length);
      return {
        text,
        caret: offsets.end,
        sameLine: Math.abs(caret.top - last.top) < 8,
        nearEnd: Math.abs(caret.left - last.right) < 16,
      };
    });
    assert.equal(beforeDelete.text, SENTENCE);
    assert.equal(beforeDelete.caret, SENTENCE.length);
    assert.equal(beforeDelete.sameLine, true, "caret line does not match the last visible character");
    assert.equal(beforeDelete.nearEnd, true, "caret is not at the end of the last visible character");

    for (let i = 0; i < 8; i += 1) await page.keyboard.press("Backspace");
    const deleted = await page.evaluate(() => document.getElementById("editor").textContent);
    assert.equal(deleted, SENTENCE.slice(0, -8));

    const middle = deleted.indexOf("tell");
    await page.evaluate((index) => {
      const editor = document.getElementById("editor");
      editor.focus();
      window.setSelectionOffsets(editor, index, index);
    }, middle);
    await page.keyboard.type("QQ");
    const inserted = await page.evaluate(() => document.getElementById("editor").textContent);
    assert.equal(inserted.slice(middle, middle + 2), "QQ");

    await page.evaluate(() => {
      const editor = document.getElementById("editor");
      window.setSelectionOffsets(editor, 0, 0);
    });
    await page.keyboard.type("Z");
    const atStart = await page.evaluate(() => document.getElementById("editor").textContent);
    assert.equal(atStart.startsWith("Z"), true);

    await page.keyboard.down("Backspace");
    await new Promise((resolve) => setTimeout(resolve, 250));
    await page.keyboard.up("Backspace");
    const held = await page.evaluate(() => document.getElementById("editor").textContent);
    assert.equal(held.startsWith("Z"), false);
    assert.equal(held.includes("QQ"), true);
    assert.equal(typeof oldLayers.caretTop, "number");
  } finally {
    await browser.close();
  }
});
