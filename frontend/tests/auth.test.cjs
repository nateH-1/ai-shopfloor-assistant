const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function loadSource(filename, globals = {}) {
  const source = readFileSync(path.join(__dirname, "../src", filename), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  });
  const context = { exports: {}, require, URL, URLSearchParams, ...globals };
  vm.runInNewContext(outputText, context);
  return context.exports;
}

test("return destinations stay inside the app and avoid login loops", () => {
  const { safeReturnPath } = loadSource("lib/authNavigation.ts");
  for (const input of [null, "https://example.com", "//example.com", "/\\example.com", "/", "/login", "/login?next=/settings", "/settings/../login", "/\n/example.com"]) {
    assert.equal(safeReturnPath(input), "/chat", String(input));
  }
  assert.equal(safeReturnPath("/settings?tab=documents#uploads"), "/settings?tab=documents#uploads");
});

test("switching between signup and login preserves the return destination", () => {
  const navigation = loadSource("lib/authNavigation.ts", {
    window: { location: { search: "?next=%2Fsettings%3Ftab%3Ddocuments" } },
  });
  assert.equal(navigation.getAuthPagePath("/"), "/?next=%2Fsettings%3Ftab%3Ddocuments");
  assert.equal(navigation.getAuthPagePath("/login"), "/login?next=%2Fsettings%3Ftab%3Ddocuments");
  assert.equal(navigation.getPostAuthPath(), "/settings?tab=documents");
});

test("a missing session raises the error used for login redirects", async () => {
  const api = loadSource("lib/authApi.ts", {
    fetch: async () => ({ status: 401, ok: false, json: async () => ({ error: "Please log in." }) }),
  });
  await assert.rejects(api.get_verification_status(), api.AuthenticationRequiredError);
});

test("signed-in pending and rejected users are not treated as signed out", async () => {
  for (const verification_status of ["PENDING", "REJECTED", "VERIFIED"]) {
    const api = loadSource("lib/authApi.ts", {
      fetch: async (url, options) => {
        assert.equal(url, "/users/verification-status");
        assert.equal(options.credentials, "same-origin");
        assert.equal(options.cache, "no-store");
        return { status: 200, ok: true, json: async () => ({ verification_status }) };
      },
    });
    assert.equal((await api.get_verification_status()).verification_status, verification_status);
  }
});

test("server failures and malformed responses do not trigger login redirects", async () => {
  for (const response of [
    { status: 500, ok: false, json: async () => ({ error: "Unavailable" }) },
    { status: 200, ok: true, json: async () => null },
  ]) {
    const api = loadSource("lib/authApi.ts", { fetch: async () => response });
    await assert.rejects(api.get_verification_status(), (error) => !(error instanceof api.AuthenticationRequiredError));
  }
});

test("protected content stays hidden before session verification; auth pages stay public", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  for (const pathname of ["/", "/login", "/chat", "/settings"]) {
    const { default: AuthGuard } = loadSource("components/AuthGuard.tsx", {
      require: (name) => {
        if (name === "next/navigation") return { usePathname: () => pathname, useRouter: () => ({ replace() {} }) };
        if (name === "@/lib/authApi") return {};
        return require(name);
      },
    });
    const html = renderToStaticMarkup(React.createElement(AuthGuard, null, "page-content"));
    assert.equal(html.includes("page-content"), pathname === "/" || pathname === "/login");
  }
});
