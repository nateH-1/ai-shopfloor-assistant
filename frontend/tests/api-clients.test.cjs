const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

class TabSessionError extends Error {}

function loadClient(filename, { tabFetch, fetch } = {}) {
  const source = readFileSync(path.join(__dirname, "../src/lib", filename), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const requests = [];
  const context = {
    exports: {},
    process: { env: {} },
    FormData,
    File,
    Blob,
    AbortSignal,
    fetch: fetch ?? (async () => {
      throw new Error("unexpected fetch");
    }),
    require: (name) => {
      assert.equal(name, "./tabSession");
      return {
        TabSessionError,
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

test("sendMessage returns the chat reply on success", async () => {
  const { api, requests } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ reply: "hello back", sources: [] }),
    }),
  });
  const result = await api.sendMessage("hello", [{ role: "user", content: "hi" }], "session-1");
  assert.equal(result.reply, "hello back");
  assert.equal(requests[0].url, "/api/chat");
  assert.equal(requests[0].init.method, "POST");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    message: "hello",
    history: [{ role: "user", content: "hi" }],
    session_id: "session-1",
  });
});

test("sendMessage throws the JSON error message when chat fails", async () => {
  const { api } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "Assistant unavailable" }),
      text: async () => "",
    }),
  });
  await assert.rejects(api.sendMessage("hello"), /Assistant unavailable/);
});

test("sendMessage falls back to the status when error JSON is missing", async () => {
  const { api } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
      text: async () => "plain failure",
    }),
  });
  await assert.rejects(api.sendMessage("hello"), /plain failure/);
});

test("listDocuments returns the documents array", async () => {
  const documents = [{ filename: "manual.pdf", chunks: 3 }];
  const { api } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ documents }),
    }),
  });
  assert.equal(JSON.stringify(await api.listDocuments()), JSON.stringify(documents));
});

test("listDocuments throws when the list request fails", async () => {
  const { api } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 500,
      text: async () => "store down",
    }),
  });
  await assert.rejects(api.listDocuments(), /Failed to list documents \(500\): store down/);
});

test("uploadDocument throws the backend message on failure", async () => {
  const { api } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 400,
      json: async () => ({ message: "Unsupported file type" }),
    }),
  });
  await assert.rejects(
    api.uploadDocument(new File(["content"], "notes.exe")),
    /Unsupported file type/,
  );
});

test("deleteDocument encodes special characters and throws on failure", async () => {
  const { api, requests } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 404,
      json: async () => ({ message: "Document not found" }),
    }),
  });
  await assert.rejects(api.deleteDocument("report#1 & notes.pdf"), /Document not found/);
  assert.equal(requests[0].url, "/api/documents/report%231%20%26%20notes.pdf");
  assert.equal(requests[0].init.method, "DELETE");
});

test("verify_user refreshes the users list after a successful update", async () => {
  const { api, requests } = loadClient("settingsAPI.ts", {
    tabFetch: async (url) => {
      if (url === "/users/verify") {
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
      }
      if (url === "/users") {
        return { ok: true, status: 200, json: async () => ({ users: [{ user_id: "u1" }] }) };
      }
      throw new Error(`unexpected url ${url}`);
    },
  });
  const users = await api.verify_user("u1", "VERIFIED");
  assert.equal(JSON.stringify(users), JSON.stringify({ users: [{ user_id: "u1" }] }));
  assert.equal(requests[0].url, "/users/verify");
  assert.equal(requests[1].url, "/users");
});

test("change_user_role succeeds for an accepted update", async () => {
  const { api, requests } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }),
  });
  await assert.doesNotReject(api.change_user_role("u1", "Admin"));
  assert.equal(requests[0].url, "/users/change-role");
  assert.deepEqual(JSON.parse(requests[0].init.body), { user_id: "u1", role: "Admin" });
});

test("change_user_role throws when the backend rejects the change", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 403,
      json: async () => ({ error: "Admins only" }),
    }),
  });
  await assert.rejects(api.change_user_role("u1", "Admin"), /Admins only/);
});

test("delete_user throws when the backend rejects the delete", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: "Cannot delete yourself" }),
    }),
  });
  await assert.rejects(api.delete_user("u1"), /Cannot delete yourself/);
});

test("get_guest_status rejects an invalid payload", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ guests_enabled: "yes" }),
    }),
  });
  await assert.rejects(api.get_guest_status(), /invalid guest status/);
});

test("requestFeedback returns null for a missing feedback record", async () => {
  const { api } = loadClient("feedbackApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 404,
      json: async () => ({ error: "not found" }),
    }),
  });
  assert.equal(await api.requestFeedback("answer-1", "GET"), null);
});

test("requestFeedback returns saved feedback after a successful PUT", async () => {
  const feedback = { vote: "helpful", reason: "", comment: "clear", updated_at: "2026-01-01T00:00:00Z" };
  const { api, requests } = loadClient("feedbackApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ feedback }),
    }),
  });
  assert.equal(
    JSON.stringify(await api.requestFeedback("answer-1", "PUT", {
      vote: "helpful",
      reason: "",
      comment: "clear",
    })),
    JSON.stringify(feedback),
  );
  assert.equal(requests[0].url, "/api/feedback/answer-1");
  assert.equal(requests[0].init.method, "PUT");
});

test("rewriteFeedback throws when the rewrite request fails", async () => {
  const { api } = loadClient("feedbackApi.ts", {
    fetch: async () => ({
      ok: false,
      status: 500,
      json: async () => ({ error: "Rewrite failed" }),
    }),
  });
  await assert.rejects(api.rewriteFeedback("answer-1"), /Rewrite failed/);
});

test("authenticate login succeeds when the response includes a user_id", async () => {
  const { api, requests } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ user_id: "u1" }),
    }),
  });
  await api.authenticate("login", { email: "user@example.com", password: "secret", role: "Worker" });
  assert.equal(requests[0].url, "/users/login");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    username: "user@example.com",
    password: "secret",
    role: "Worker",
  });
});

test("authenticate login throws the backend error message", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 401,
      json: async () => ({ error: "Invalid credentials" }),
    }),
  });
  await assert.rejects(
    api.authenticate("login", { email: "user@example.com", password: "bad", role: "Worker" }),
    /Invalid credentials/,
  );
});

test("authenticate register includes the trimmed full name", async () => {
  const { api, requests } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ user_id: "u2" }),
    }),
  });
  await api.authenticate("register", {
    email: "new@example.com",
    password: "secret",
    role: "Worker",
    full_name: "  Nate Haile  ",
  });
  assert.equal(requests[0].url, "/users/register");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    username: "new@example.com",
    password: "secret",
    role: "Worker",
    full_name: "Nate Haile",
  });
});

test("logout throws when the logout request fails", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 500,
      json: async () => ({ error: "Logout failed" }),
    }),
  });
  await assert.rejects(api.logout(), /Logout failed/);
});

test("enable_guest returns the updated guest status", async () => {
  const { api, requests } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ guests_enabled: true }),
    }),
  });
  assert.deepEqual(await api.enable_guest("enabled"), { guests_enabled: true });
  assert.equal(requests[0].url, "/guest/enable");
  assert.deepEqual(JSON.parse(requests[0].init.body), { enabled: "enabled" });
});

test("enable_guest rejects an invalid payload", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ guests_enabled: "true" }),
    }),
  });
  await assert.rejects(api.enable_guest("enabled"), /invalid guest status/);
});

test("get_role_permissions returns the backend payload on success", async () => {
  const payload = { Worker: ["chat"], Admin: ["chat", "settings"] };
  const { api, requests } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
  });
  assert.equal(JSON.stringify(await api.get_role_permissions()), JSON.stringify(payload));
  assert.equal(requests[0].url, "/roles/permissions");
  assert.equal(requests[0].init.method, "POST");
});

test("get_role_permissions throws when the backend rejects the request", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 403,
      json: async () => ({ error: "Forbidden" }),
    }),
  });
  await assert.rejects(api.get_role_permissions(), /Forbidden/);
});

test("uploadDocument returns the backend payload on success", async () => {
  const payload = { filename: "manual.pdf", chunks: 4, message: "ok" };
  const { api, requests } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
  });
  assert.equal(
    JSON.stringify(await api.uploadDocument(new File(["pdf"], "manual.pdf"))),
    JSON.stringify(payload),
  );
  assert.equal(requests[0].url, "/api/documents/upload");
  assert.equal(requests[0].init.method, "POST");
  assert.ok(requests[0].init.body instanceof FormData);
});

test("transcribeAudio returns the transcript text", async () => {
  const { api, requests } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ text: "hello shopfloor" }),
    }),
  });
  assert.equal(await api.transcribeAudio(new Blob(["audio"]), "clip.webm"), "hello shopfloor");
  assert.equal(requests[0].url, "/api/transcribe");
  assert.ok(requests[0].init.body instanceof FormData);
});

test("transcribeAudio throws when the response has no text", async () => {
  const { api } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
    }),
  });
  await assert.rejects(api.transcribeAudio(new Blob(["audio"])), /No transcription text returned/);
});

test("invalid verification status is rejected", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ verification_status: "UNKNOWN" }),
    }),
  });
  await assert.rejects(api.get_verification_status(), /invalid verification status/);
});

test("logout success completes quietly", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => ({ ok: true, status: 204, json: async () => null }),
  });
  await assert.doesNotReject(api.logout());
});

test("authenticate fails when user_id is missing", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }),
  });
  await assert.rejects(
    api.authenticate("login", { email: "user@example.com", password: "secret", role: "Worker" }),
    /Authentication failed/,
  );
});

test("unreachable server during login throws a clear error", async () => {
  const { api } = loadClient("authApi.ts", {
    tabFetch: async () => {
      throw new Error("network down");
    },
  });
  await assert.rejects(
    api.authenticate("login", { email: "user@example.com", password: "secret", role: "Worker" }),
    /Unable to reach the server/,
  );
});

test("deleteDocument success returns the backend payload", async () => {
  const payload = { success: true, message: "deleted" };
  const { api } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
  });
  assert.equal(JSON.stringify(await api.deleteDocument("manual.pdf")), JSON.stringify(payload));
});

test("listDocuments returns undefined when documents is missing", async () => {
  const { api } = loadClient("documentApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({}),
    }),
  });
  assert.equal(await api.listDocuments(), undefined);
});

test("sendMessage omits session_id when it is not provided", async () => {
  const { api, requests } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ reply: "ok", sources: [] }),
    }),
  });
  await api.sendMessage("hello");
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    message: "hello",
    history: [],
  });
});

test("transcribeAudio failure throws the backend error", async () => {
  const { api } = loadClient("chatApi.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "Speech service unavailable" }),
      text: async () => "",
    }),
  });
  await assert.rejects(api.transcribeAudio(new Blob(["audio"])), /Speech service unavailable/);
});

test("get_users success returns the payload", async () => {
  const payload = { users: [{ user_id: "u1" }] };
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
  });
  assert.equal(JSON.stringify(await api.get_users()), JSON.stringify(payload));
});

test("get_users failure throws", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: false,
      status: 500,
      json: async () => ({ error: "Users unavailable" }),
    }),
  });
  await assert.rejects(api.get_users(), /Users unavailable/);
});

test("get_guest_status success returns a boolean flag", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ guests_enabled: false }),
    }),
  });
  assert.deepEqual(await api.get_guest_status(), { guests_enabled: false });
});

test("delete_user success completes quietly", async () => {
  const { api } = loadClient("settingsAPI.ts", {
    tabFetch: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }),
  });
  await assert.doesNotReject(api.delete_user("u1"));
});
