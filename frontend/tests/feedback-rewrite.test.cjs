// Exercise the existing component handlers without adding a browser/test dependency.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const saved = { vote: 'not_helpful', reason: 'unclear', comment: 'Old comment', updated_at: 'now' };
const nextTurn = () => new Promise(resolve => setImmediate(resolve));

function render(requestFeedback, changed = true) {
  const states = [saved, 'not_helpful', false, false, true, 'incomplete',
    changed ? 'Make it more detailed' : saved.comment, '', '', false];
  if (!changed) states[5] = saved.reason;
  let index = 0;
  const rewrites = [];
  const jsx = (type, props) => ({ type, props });
  const react = {
    useState: () => { const i = index++; return [states[i], value => { states[i] = value; }]; },
    useRef: value => ({ current: value }), useId: () => 'feedback', useEffect: () => {},
  };
  const filename = path.join(__dirname, '../src/components/AnswerFeedback.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, Error, require: name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name === '@/lib/feedbackApi') return { requestFeedback };
    throw new Error(`Unexpected dependency ${name}`);
  }});
  const tree = exports.default({ messageId: 'selected-older-answer', answerText: 'Original',
    onRewrite: feedback => rewrites.push(feedback) });
  function find(node) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'button' && /^(Save and rewrite|Rewrite now)$/.test(node.props.children)) return node;
    for (const child of [node.props?.children].flat(Infinity)) {
      const found = find(child); if (found) return found;
    }
  }
  return { button: find(tree), rewrites, states };
}

test('Save and rewrite waits for successful latest save on selected older answer', async () => {
  let resolveSave;
  const latest = { ...saved, reason: 'incomplete', comment: 'Make it more detailed' };
  const calls = [];
  const ui = render((...args) => { calls.push(args); return new Promise(resolve => { resolveSave = resolve; }); });
  ui.button.props.onClick();
  assert.equal(ui.rewrites.length, 0);
  assert.equal(calls[0][0], 'selected-older-answer');
  assert.equal(calls[0][1], 'PUT');
  assert.equal(calls[0][2].reason, 'incomplete');
  assert.equal(calls[0][2].comment, 'Make it more detailed');
  resolveSave(latest);
  await nextTurn();
  assert.equal(ui.rewrites[0], latest);
});

test('failed save blocks rewrite instead of using older feedback', async () => {
  const ui = render(async () => { throw new Error('Save failed'); });
  ui.button.props.onClick(); await nextTurn();
  assert.equal(ui.rewrites.length, 0);
  assert.equal(ui.states[7], 'Save failed');
});

test('null save response also blocks rewrite', async () => {
  const ui = render(async () => null);
  ui.button.props.onClick(); await nextTurn();
  assert.equal(ui.rewrites.length, 0);
});

test('unchanged saved feedback rewrites without an unnecessary save', async () => {
  const ui = render(() => { throw new Error('Should not save'); }, false);
  ui.button.props.onClick(); await nextTurn();
  assert.equal(ui.rewrites[0], saved);
});
