const assert = require("node:assert/strict");
const { randomUUID } = require("node:crypto");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "../src/lib/tabSession.ts"), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
});
const storageKey = "shopfloor.tab_id";
const tick = () => new Promise((resolve) => setImmediate(resolve));

// Model queued Web Locks across separate browser documents, including lifetime
// locks whose callbacks remain pending until pagehide.
function lockManager() {
  const held = new Set();
  const queues = new Map();
  return {
    request(name, options, callback) {
      if (typeof options === "function") {
        callback = options;
        options = {};
      }
      return new Promise((resolve, reject) => {
        const run = () => {
          held.add(name);
          Promise.resolve().then(() => callback({ name })).then(resolve, reject).finally(() => {
            held.delete(name);
            const next = queues.get(name)?.shift();
            if (next) next();
          });
        };
        if (held.has(name)) {
          if (options.ifAvailable) {
            Promise.resolve().then(() => callback(null)).then(resolve, reject);
          } else {
            if (!queues.has(name)) queues.set(name, []);
            queues.get(name).push(run);
          }
        } else {
          run();
        }
      });
    },
  };
}

function document({ locks = lockManager(), storage = new Map(), fetch, crypto = { randomUUID } } = {}) {
  const listeners = new Map();
  const requests = [];
  const window = {
    location: { href: "http://localhost:3000/chat", origin: "http://localhost:3000" },
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(listener);
    },
  };
  const context = {
    exports: {}, window, navigator: { locks }, crypto, URL, Headers,
    sessionStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
    fetch: async (url, init) => {
      requests.push({ url, init });
      return fetch ? fetch(url, init) : { ok: true, status: 204 };
    },
  };
  vm.runInNewContext(outputText, context);
  return {
    ...context.exports, requests, storage,
    dispatch(type) {
      const handlers = listeners.get(type) ?? [];
      listeners.delete(type);
      for (const listener of handlers) listener();
    },
  };
}

test("API calls bootstrap once, preserve bodies and headers, and share this tab's ID", async () => {
  const tab = document();
  const body = new FormData();
  body.append("file", "sample");
  await Promise.all([
    tab.tabFetch("/api/documents/upload", { method: "POST", body }),
    tab.tabFetch("/users/verification-status", { headers: { Accept: "application/json", "X-Tab-ID": "override" } }),
  ]);
  assert.equal(tab.requests.filter(({ url }) => url === "/users/session").length, 1);
  assert.equal(tab.requests[0].url, "/users/session");
  const tabId = tab.storage.get(storageKey);
  assert.match(tabId, /^[0-9a-f-]{36}$/);
  for (const { init } of tab.requests) {
    assert.equal(new Headers(init.headers).get("X-Tab-ID"), tabId);
    assert.equal(init.credentials, "same-origin");
    assert.equal(init.cache, "no-store");
  }
  assert.equal(tab.requests.find(({ url }) => url.endsWith("upload")).init.body, body);
  assert.equal(tab.requests.find(({ url }) => url.endsWith("status")).init.headers.get("Accept"), "application/json");
  tab.dispatch("pagehide");
});

test("new and duplicated tabs claim distinct IDs without changing the source tab", async () => {
  const locks = lockManager();
  const first = document({ locks });
  await first.tabFetch("/users/login");
  const originalId = first.storage.get(storageKey);
  const duplicate = document({ locks, storage: new Map(first.storage) });
  const fresh = document({ locks });
  await Promise.all([duplicate.tabFetch("/users/login"), fresh.tabFetch("/users/login")]);
  const ids = [originalId, duplicate.storage.get(storageKey), fresh.storage.get(storageKey)];
  assert.equal(new Set(ids).size, 3);
  await first.tabFetch("/users/verification-status");
  assert.equal(first.requests.at(-1).init.headers.get("X-Tab-ID"), originalId);
  for (const tab of [first, duplicate, fresh]) tab.dispatch("pagehide");
});

test("reload keeps the tab ID once the old document releases its claim", async () => {
  const locks = lockManager();
  const first = document({ locks });
  await first.tabFetch("/users/login");
  const originalId = first.storage.get(storageKey);
  first.dispatch("pagehide");
  await tick();
  const reloaded = document({ locks, storage: first.storage });
  await reloaded.tabFetch("/users/verification-status");
  assert.equal(reloaded.storage.get(storageKey), originalId);
  reloaded.dispatch("pagehide");
});

test("a restored document reclaims its ID and detects a new owner before requesting", async () => {
  const locks = lockManager();
  const first = document({ locks });
  await first.tabFetch("/users/login");
  const originalId = first.storage.get(storageKey);
  first.dispatch("pagehide");
  await tick();
  const duplicate = document({ locks, storage: new Map(first.storage) });
  await duplicate.tabFetch("/users/login");
  assert.equal(duplicate.storage.get(storageKey), originalId);
  first.dispatch("pageshow");
  await first.tabFetch("/users/verification-status");
  assert.notEqual(first.storage.get(storageKey), originalId);
  assert.equal(first.requests.filter(({ url }) => url === "/users/session").length, 2);
  first.dispatch("pagehide");
  duplicate.dispatch("pagehide");
});

test("a mutation awaiting bootstrap aborts if pagehide releases its tab claim", async () => {
  const locks = lockManager();
  let finishBootstrap;
  let bootstrapStarted;
  const started = new Promise((resolve) => { bootstrapStarted = resolve; });
  const tab = document({
    locks,
    fetch: async (url) => {
      if (url === "/users/session") {
        bootstrapStarted();
        await new Promise((resolve) => { finishBootstrap = resolve; });
      }
      return { ok: true, status: 204 };
    },
  });
  const pending = tab.tabFetch("/users/logout", { method: "POST" });
  await started;
  const originalId = tab.storage.get(storageKey);
  tab.dispatch("pagehide");
  await tick();

  // The original document is frozen while a copied document claims the old ID.
  const copy = document({ locks, storage: new Map(tab.storage) });
  const copyRequest = copy.tabFetch("/users/verification-status");
  await tick();
  assert.equal(copy.storage.get(storageKey), originalId);
  finishBootstrap();
  await assert.rejects(pending, /session changed.*Reload/);
  await copyRequest;
  assert.deepEqual(tab.requests.map(({ url }) => url), ["/users/session"]);
  copy.dispatch("pagehide");
});

test("a released claim does not bootstrap after waiting for another tab's browser lock", async () => {
  const locks = lockManager();
  let releaseBrowser;
  const blocker = locks.request("shopfloor.browser-session", () => new Promise((resolve) => { releaseBrowser = resolve; }));
  await tick();
  const tab = document({ locks });
  const pending = tab.tabFetch("/users/login", { method: "POST" });
  await tick();
  tab.dispatch("pagehide");
  releaseBrowser();
  await blocker;
  await assert.rejects(pending, /session changed.*Reload/);
  assert.equal(tab.requests.length, 0);
});

test("simultaneous first visits serialize browser-cookie initialization", async () => {
  const locks = lockManager();
  let cookie;
  let active = 0;
  let maxActive = 0;
  let cookieWrites = 0;
  const fetch = async (url) => {
    if (url === "/users/session") {
      active += 1;
      maxActive = Math.max(active, maxActive);
      const needsCookie = !cookie;
      await tick();
      if (needsCookie) {
        cookie = randomUUID();
        cookieWrites += 1;
      }
      active -= 1;
    } else {
      assert.ok(cookie, "authenticated request must follow initialization");
    }
    return { ok: true, status: 204 };
  };
  const first = document({ locks, fetch });
  const second = document({ locks, fetch });
  await Promise.all([first.tabFetch("/users/login"), second.tabFetch("/users/login")]);
  assert.equal(maxActive, 1);
  assert.equal(cookieWrites, 1);
  first.dispatch("pagehide");
  second.dispatch("pagehide");
});

test("bootstrap failures can be retried without sending the protected request", async () => {
  let ready = false;
  const tab = document({ fetch: async () => ({ ok: ready, status: ready ? 204 : 503 }) });
  await assert.rejects(tab.tabFetch("/users/login"), tab.TabSessionError);
  assert.equal(tab.requests.length, 1);
  ready = true;
  await tab.tabFetch("/users/login");
  assert.deepEqual(tab.requests.map(({ url }) => url), ["/users/session", "/users/session", "/users/login"]);
  tab.dispatch("pagehide");
});

test("sign-in can reinitialize a cleared cookie without reloading the tab", async () => {
  let cookie;
  const tab = document({
    fetch: async (url) => {
      if (url === "/users/session") cookie ??= randomUUID();
      else assert.ok(cookie, "sign-in needs the current browser cookie");
      return { ok: true, status: 204 };
    },
  });
  await tab.tabFetch("/users/login", { method: "POST" }, { refreshBrowserSession: true });
  const tabId = tab.storage.get(storageKey);
  cookie = undefined;
  await tab.tabFetch("/users/login", { method: "POST" }, { refreshBrowserSession: true });
  assert.equal(tab.requests.filter(({ url }) => url === "/users/session").length, 2);
  assert.equal(tab.storage.get(storageKey), tabId);
  tab.dispatch("pagehide");
});

test("unsupported browsers and foreign origins fail before sending identity", async () => {
  const unsupported = document({ locks: null });
  await assert.rejects(unsupported.tabFetch("/users/login"), /HTTPS or localhost/);
  assert.equal(unsupported.requests.length, 0);
  const tab = document();
  await assert.rejects(tab.tabFetch("https://elsewhere.example/users/login"), /same-origin/);
  assert.equal(tab.requests.length, 0);
});

test("account, document, chat, and feedback clients all send the selected tab's identity", async () => {
  const tab = document({
    fetch: async () => ({
      ok: true, status: 200,
      json: async () => ({ user_id: randomUUID(), verification_status: "VERIFIED", documents: [], text: "hello", feedback: null }),
    }),
  });
  function client(filename) {
    const input = readFileSync(path.join(__dirname, "../src/lib", filename), "utf8");
    const compiled = ts.transpileModule(input, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
    const context = {
      exports: {}, process: { env: {} }, FormData, AbortSignal,
      require: (name) => {
        assert.equal(name, "./tabSession");
        return tab;
      },
    };
    vm.runInNewContext(compiled.outputText, context);
    return context.exports;
  }
  const auth = client("authApi.ts");
  await auth.authenticate("login", { email: "user@example.com", password: "password", role: "Worker" });
  await auth.authenticate("register", { email: "", password: "", role: "Guest" });
  await auth.get_verification_status();
  const settings = client("settingsAPI.ts");
  await settings.get_role_permissions();
  await settings.get_users();
  await settings.verify_user("user", "VERIFIED");
  await settings.change_user_role("user", "Worker");
  await settings.delete_user("user");
  const documents = client("documentApi.ts");
  await documents.listDocuments();
  await documents.uploadDocument(new File(["content"], "manual.pdf"));
  await documents.deleteDocument("manual.pdf");
  const chat = client("chatApi.ts");
  await chat.sendMessage("hello");
  await chat.transcribeAudio(new Blob(["audio"]));
  await client("feedbackApi.ts").requestFeedback("answer-id");
  await auth.logout();

  assert.equal(tab.requests.filter(({ url }) => url === "/users/session").length, 2);
  for (const { init } of tab.requests) {
    assert.equal(new Headers(init.headers).get("X-Tab-ID"), tab.storage.get(storageKey));
    assert.equal(init.credentials, "same-origin");
  }
  tab.dispatch("pagehide");
});
