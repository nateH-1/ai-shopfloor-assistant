/** Only allow return destinations within this app, excluding the public auth pages. */
export function safeReturnPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020]/.test(value)) {
    return "/chat";
  }
  const base = "https://app.local";
  const destination = new URL(value, base);
  if (destination.origin !== base || destination.pathname === "/" || /^\/login\/?$/.test(destination.pathname)) {
    return "/chat";
  }
  return destination.pathname + destination.search + destination.hash;
}

/** Called from browser event handlers after login or signup. */
export function getPostAuthPath(): string {
  return safeReturnPath(new URLSearchParams(window.location.search).get("next"));
}

export function getAuthPagePath(page: "/" | "/login"): string {
  return `${page}?next=${encodeURIComponent(getPostAuthPath())}`;
}
