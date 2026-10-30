/** Forward the browser credential and tab selector to Flask, never user claims. */
export function authHeaders(request: Request, initial?: HeadersInit): Headers {
  const headers = new Headers(initial);
  for (const name of ["Cookie", "X-Tab-ID"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}
