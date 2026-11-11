const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// Run component effects and handlers without adding a DOM/test dependency.
function component(filename, dependencies, globals = {}) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const same = (left, right) => left && right && left.length === right.length && left.every((v, i) => Object.is(v, right[i]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { value: typeof initial === "function" ? initial() : initial };
      return [slots[index].value, next => {
        slots[index].value = typeof next === "function" ? next(slots[index].value) : next;
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(callback, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) slots[index] = { value: callback, deps };
      return slots[index].value;
    },
    useEffect(create, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) {
        effects.push(() => {
          slots[index]?.cleanup?.();
          slots[index] = { deps, cleanup: create() };
        });
      }
    },
    createContext: () => ({ Provider: "context-provider" }),
  };
  const jsx = (type, props) => ({ type, props });
  const cache = new Map();
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative);
    const code = ts.transpileModule(readFileSync(path.join(__dirname, "../src", relative), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
    }).outputText;
    const exports = {};
    cache.set(relative, exports);
    vm.runInNewContext(code, {
      exports, Error, ...globals,
      require(name) {
        if (name === "react") return react;
        if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
        if (Object.hasOwn(dependencies, name)) return dependencies[name];
        if (name.startsWith("@/")) return load(`${name.slice(2)}.ts`);
        if (name.startsWith(".")) return load(`${path.posix.join(path.posix.dirname(relative), name)}.ts`);
        throw new Error(`Unexpected dependency ${name}`);
      },
    });
    return exports;
  }
  const renderComponent = load(filename).default;
  return {
    render(props = {}) { cursor = 0; effects = []; return renderComponent(props); },
    flushEffects() { const pending = effects; effects = []; pending.forEach(effect => effect()); },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(Infinity)) {
    const found = find(child, predicate);
    if (found) return found;
  }
  return null;
}

function eventTarget() {
  const listeners = [];
  return {
    listeners,
    addEventListener(type, handler, options = {}) { listeners.push({ type, handler, capture: Boolean(options.capture) }); },
    removeEventListener(type, handler) {
      const index = listeners.findIndex(entry => entry.type === type && entry.handler === handler);
      if (index !== -1) listeners.splice(index, 1);
    },
    dispatch(type) { listeners.filter(entry => entry.type === type).forEach(entry => entry.handler()); },
  };
}

test("Settings saves on hidden, pagehide capture, and route exit, then removes listeners", async () => {
  let saves = 0;
  const window = eventTarget();
  const document = { ...eventTarget(), visibilityState: "visible" };
  const dummy = { default: () => null };
  const ui = component("app/settings/page.tsx", {
    "@/components/Header": dummy,
    "@/components/UserManagementBubble": dummy,
    "@/components/DocumentBubble": dummy,
    "@/components/GeneralBubble": dummy,
    "@/components/GuestManagementBubble": dummy,
    "@/components/ThemeProvider": { useTheme: () => ({ saveTheme: async () => { saves++; } }) },
    "@/lib/authApi": { get_verification_status: async () => ({ verification_status: "PENDING" }) },
    "@/lib/settingsAPI": { get_role_permissions: async () => ({}) },
  }, { window, document });
  ui.render(); ui.flushEffects();
  assert.equal(saves, 0);
  document.dispatch("visibilitychange");
  assert.equal(saves, 0);
  document.visibilityState = "hidden";
  document.dispatch("visibilitychange");
  assert.equal(saves, 1);
  assert.equal(window.listeners.find(entry => entry.type === "pagehide").capture, true);
  window.dispatch("pagehide");
  assert.equal(saves, 2);
  ui.unmount();
  assert.equal(saves, 3);
  assert.equal(window.listeners.length, 0);
  assert.equal(document.listeners.length, 0);
  await tick();
});

test("logout waits for the theme save and logout response before navigating", async () => {
  const save = deferred();
  const logout = deferred();
  const calls = [];
  const ui = component("components/GeneralBubble.tsx", {
    "./ThemeToggle": { default: () => null },
    "./ThemeProvider": { useTheme: () => ({ saveTheme: () => { calls.push("save"); return save.promise; } }) },
    "@/lib/authApi": { logout: () => { calls.push("logout"); return logout.promise; } },
  }, { window: { location: { replace: path => calls.push(path) } } });
  find(ui.render(), node => node.type === "button").props.onClick();
  assert.deepEqual(calls, ["save"]);
  assert.equal(find(ui.render(), node => node.type === "fieldset").props.disabled, true);
  save.resolve(); await tick();
  assert.deepEqual(calls, ["save", "logout"]);
  logout.resolve(); await tick();
  assert.deepEqual(calls, ["save", "logout", "/login"]);
});

test("a failed theme save keeps the user signed in and displays an actionable error", async () => {
  let loggedOut = false;
  const ui = component("components/GeneralBubble.tsx", {
    "./ThemeToggle": { default: () => null },
    "./ThemeProvider": { useTheme: () => ({ saveTheme: async () => { throw new Error("Theme save failed. Try again."); } }) },
    "@/lib/authApi": { logout: async () => { loggedOut = true; } },
  }, { window: { location: { replace: () => assert.fail("must not navigate") } } });
  find(ui.render(), node => node.type === "button").props.onClick();
  await tick();
  const tree = ui.render();
  assert.equal(loggedOut, false);
  assert.equal(find(tree, node => node.props?.role === "alert").props.children, "Theme save failed. Try again.");
  assert.equal(find(tree, node => node.type === "button").props.disabled, false);
  assert.equal(find(tree, node => node.type === "fieldset").props.disabled, false);
});

test("AuthGuard restores account theme before showing protected content and resets on public pages", async () => {
  let pathname = "/chat";
  const restored = deferred();
  const calls = [];
  const router = { replace: () => assert.fail("valid login must not redirect") };
  const theme = {
    loadAccountTheme: () => { calls.push("theme"); return restored.promise; },
    resetAccountTheme: () => calls.push("reset"),
  };
  const ui = component("components/AuthGuard.tsx", {
    "next/navigation": { usePathname: () => pathname, useRouter: () => router },
    "./ThemeProvider": { useTheme: () => theme },
    "@/lib/authApi": {
      AuthenticationRequiredError: class extends Error {},
      get_verification_status: async () => { calls.push("session"); return { verification_status: "VERIFIED" }; },
    },
  });
  assert.notEqual(ui.render({ children: "protected-content" }), "protected-content");
  ui.flushEffects(); await tick();
  assert.deepEqual(calls, ["session", "theme"]);
  assert.notEqual(ui.render({ children: "protected-content" }), "protected-content");
  restored.resolve(); await tick();
  assert.equal(ui.render({ children: "protected-content" }), "protected-content");
  pathname = "/login";
  assert.equal(ui.render({ children: "login-form" }), "login-form");
  ui.flushEffects();
  assert.deepEqual(calls, ["session", "theme", "reset"]);
  ui.unmount();
});

test("account theme restores with blocked storage and stale save errors do not follow another login", async () => {
  const failedSave = deferred();
  const classes = new Set();
  const window = {
    ...eventTarget(),
    localStorage: { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  };
  const document = { documentElement: { classList: { toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); } } } };
  const ui = component("components/ThemeProvider.tsx", {
    "@/lib/themeApi": {
      getThemePreference: async () => ({ theme: "red", user_id: "user-a", login_id: "login-a" }),
      saveThemePreference: () => failedSave.promise,
    },
  }, { window, document });
  let tree = ui.render({ children: "content" }); ui.flushEffects();
  await tree.props.value.loadAccountTheme();
  tree = ui.render({ children: "content" });
  assert.equal(tree.props.value.theme, "red");
  assert.equal(classes.has("red"), true);
  tree.props.value.setTheme("dark");
  const saving = tree.props.value.saveTheme();
  tree.props.value.resetAccountTheme();
  failedSave.reject(new Error("Old account save failed"));
  await assert.rejects(saving, /Old account save failed/);
  assert.equal(find(ui.render({ children: "content" }), node => node.props?.role === "alert"), null);
  ui.unmount();
});
