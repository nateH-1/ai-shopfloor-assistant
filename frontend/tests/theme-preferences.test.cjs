const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function loadModule(filename, dependencies = {}) {
  const source = readFileSync(path.join(__dirname, "../src/lib", filename), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const exports = {};
  vm.runInNewContext(outputText, {
    exports,
    require: (name) => {
      if (name in dependencies) return dependencies[name];
      throw new Error(`Unexpected runtime dependency: ${name}`);
    },
  });
  return exports;
}

const loadController = () => loadModule("themePreferences.ts").createThemePreferences;
class AuthenticationRequiredError extends Error {}
const loadApi = tabFetch => loadModule("themeApi.ts", {
  "./tabSession": { tabFetch },
  "./theme": loadModule("theme.ts"),
  "./authApi": { AuthenticationRequiredError },
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const tick = () => new Promise(resolve => setImmediate(resolve));
const account = (theme = "light", user_id = "alice", login_id = "alice-login") => ({ theme, user_id, login_id });

function setup(overrides = {}) {
  const applied = [];
  const writes = [];
  const controller = loadController()({
    read: async () => account(),
    write: async (identity, theme) => { writes.push({ ...identity, theme }); },
    apply: theme => applied.push(theme),
    fallback: () => "dark",
    ...overrides,
  });
  return { controller, applied, writes };
}

test("login loads saved red instead of the browser fallback and shares concurrent loads", async () => {
  const pending = deferred();
  let reads = 0;
  const ui = setup({ read: () => { reads++; return pending.promise; } });
  const first = ui.controller.load();
  const second = ui.controller.load();
  assert.equal(reads, 1);
  pending.resolve(account("red"));
  await Promise.all([first, second]);
  assert.deepEqual(ui.applied, ["red"]);
  assert.equal(ui.controller.hasAccount(), true);
  await ui.controller.load();
  assert.equal(reads, 1, "navigation within the same login must not reload over an unsaved selection");
});

test("first Settings exit adopts an existing browser theme even without a new selection", async () => {
  const ui = setup({ read: async () => account(null) });
  await ui.controller.load();
  assert.deepEqual(ui.applied, ["dark"]);
  assert.deepEqual(ui.writes, [], "loading alone must not write an account preference");
  await ui.controller.save();
  assert.deepEqual(ui.writes, [{ ...account(), theme: "dark" }]);
  ui.controller.select("red");
  assert.deepEqual(ui.applied, ["dark", "red"]);
  assert.equal(ui.writes.length, 1, "selection previews locally until Settings is exited");
  await ui.controller.save();
  assert.deepEqual(ui.writes, [{ ...account(), theme: "dark" }, { ...account(), theme: "red" }]);
});

test("Settings exit persists the latest changed theme once and skips unchanged visits", async () => {
  const ui = setup();
  await ui.controller.load();
  await ui.controller.save();
  ui.controller.select("light");
  await ui.controller.save();
  assert.deepEqual(ui.writes, []);
  ui.controller.select("red");
  ui.controller.select("dark");
  await ui.controller.save();
  await ui.controller.save();
  assert.deepEqual(ui.writes, [{ ...account(), theme: "dark" }]);
});

test("guests can preview themes without attempting an account write", async () => {
  const ui = setup({ read: async () => account(null, null, "guest-login") });
  await ui.controller.load();
  assert.equal(ui.controller.hasAccount(), false);
  ui.controller.select("red");
  await ui.controller.save();
  assert.deepEqual(ui.applied, ["dark", "red"]);
  assert.deepEqual(ui.writes, []);
});

test("failed preference loads can be retried", async () => {
  let reads = 0;
  const ui = setup({ read: async () => {
    if (++reads === 1) throw new Error("Server unavailable");
    return account("red");
  } });
  await assert.rejects(ui.controller.load(), /Server unavailable/);
  assert.deepEqual(ui.applied, []);
  await ui.controller.load();
  assert.equal(reads, 2);
  assert.deepEqual(ui.applied, ["red"]);
});

test("a failed save retains the selected theme for a later retry", async () => {
  let attempts = 0;
  const ui = setup({ write: async (_identity, theme) => {
    assert.equal(theme, "red");
    if (++attempts === 1) throw new Error("Save unavailable");
  } });
  await ui.controller.load();
  ui.controller.select("red");
  await assert.rejects(ui.controller.save(), /Save unavailable/);
  assert.equal(ui.applied.at(-1), "red");
  await ui.controller.save();
  await ui.controller.save();
  assert.equal(attempts, 2);
});

test("overlapping exit saves serialize and drain changes made during the first request", async () => {
  const firstWrite = deferred();
  const secondWrite = deferred();
  const writes = [];
  const ui = setup({ write: (_identity, theme) => {
    writes.push(theme);
    return writes.length === 1 ? firstWrite.promise : secondWrite.promise;
  } });
  await ui.controller.load();
  ui.controller.select("red");
  const firstSave = ui.controller.save();
  ui.controller.select("dark");
  const secondSave = ui.controller.save();
  assert.deepEqual(writes, ["red"]);
  firstWrite.resolve();
  await tick();
  assert.deepEqual(writes, ["red", "dark"]);
  secondWrite.resolve();
  await Promise.all([firstSave, secondSave]);
  await ui.controller.save();
  assert.deepEqual(writes, ["red", "dark"]);
});

test("returning to the original theme during a save still restores that value on the server", async () => {
  const pending = deferred();
  const writes = [];
  const ui = setup({ write: async (_identity, theme) => {
    writes.push(theme);
    if (writes.length === 1) await pending.promise;
  } });
  await ui.controller.load();
  ui.controller.select("red");
  const save = ui.controller.save();
  ui.controller.select("light");
  pending.resolve();
  await save;
  assert.deepEqual(writes, ["red", "light"]);
});

test("an old login's delayed load cannot replace the new account's preference", async () => {
  const oldLoad = deferred();
  const newLoad = deferred();
  let reads = 0;
  const ui = setup({ read: () => ++reads === 1 ? oldLoad.promise : newLoad.promise });
  const oldRequest = ui.controller.load();
  ui.controller.reset();
  const newRequest = ui.controller.load();
  newLoad.resolve(account("red", "bob", "bob-login"));
  await newRequest;
  oldLoad.resolve(account("dark"));
  await oldRequest;
  assert.deepEqual(ui.applied, ["red"]);
  ui.controller.select("light");
  await ui.controller.save();
  assert.deepEqual(ui.writes, [account("light", "bob", "bob-login")]);
});

test("an old login's delayed save does not drain into or overwrite the new account", async () => {
  const pending = deferred();
  const writes = [];
  let reads = 0;
  const ui = setup({
    read: async () => ++reads === 1 ? account() : account("red", "bob", "bob-login"),
    write: async (identity, theme) => {
      writes.push({ ...identity, theme });
      if (writes.length === 1) await pending.promise;
    },
  });
  await ui.controller.load();
  ui.controller.select("red");
  const oldSave = ui.controller.save();
  ui.controller.select("dark");
  ui.controller.reset();
  await ui.controller.load();
  pending.resolve();
  await oldSave;
  assert.equal(ui.applied.at(-1), "red");
  ui.controller.select("light");
  await ui.controller.save();
  assert.deepEqual(writes, [account("red"), account("light", "bob", "bob-login")]);
});

test("theme API loads account identity and rejects malformed preference responses", async () => {
  const valid = account("red");
  const api = loadApi(async url => {
    assert.equal(url, "/users/theme");
    return { ok: true, json: async () => valid };
  });
  assert.equal(await api.getThemePreference(), valid);
  for (const invalid of [null, {}, { ...valid, theme: "blue" },
    { ...valid, user_id: 42 }, { ...valid, user_id: "" },
    { ...valid, login_id: null }, { ...valid, login_id: "" }]) {
    const invalidApi = loadApi(async () => ({ ok: true, json: async () => invalid }));
    await assert.rejects(invalidApi.getThemePreference(), /invalid theme preference/);
  }
});

test("an expired login during preference loading uses the authentication redirect error", async () => {
  const api = loadApi(async () => ({ ok: false, status: 401, json: async () => ({ error: "Please log in" }) }));
  await assert.rejects(api.getThemePreference(), AuthenticationRequiredError);
});

test("theme API sends the originating account and login with a keepalive PUT", async () => {
  const api = loadApi(async (url, options) => {
    assert.equal(url, "/users/theme");
    assert.equal(options.method, "PUT");
    assert.equal(options.keepalive, true);
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(options.body), {
      theme: "red", user_id: "alice", login_id: "alice-login",
    });
    return { ok: true, json: async () => account("red") };
  });
  await api.saveThemePreference(account(), "red");
});

test("theme API propagates rejected saves and rejects a mismatched acknowledgement", async () => {
  const rejected = loadApi(async () => ({
    ok: false, status: 409, json: async () => ({ error: "Login changed" }),
  }));
  await assert.rejects(rejected.saveThemePreference(account(), "red"), /Login changed/);
  const mismatched = loadApi(async () => ({ ok: true, json: async () => account("dark") }));
  await assert.rejects(mismatched.saveThemePreference(account(), "red"), /Unable to save/);
});
