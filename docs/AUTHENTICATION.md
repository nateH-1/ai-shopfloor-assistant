# Tab-specific authentication

Each browser tab signs in independently. Refreshing a tab preserves its login;
switching accounts or logging out affects only that tab. Duplicating an active app
tab creates a new tab ID and requires a separate login.

The frontend needs a current browser with Web Locks and session storage enabled,
served over HTTPS or `http://localhost`. Use the frontend's same-origin API routes;
direct cross-origin backend requests are not supported by the client helper.

## Request flow

1. `tabFetch` claims a UUID stored in `sessionStorage` and sends it as `X-Tab-ID`.
   A Web Lock detects a copied ID already held by another tab. A separate lock
   serializes initial browser-cookie setup across tabs.
2. `POST /users/session` initializes Flask's signed HttpOnly cookie. It contains a
   random browser-session identifier, not an account ID or role.
3. Login and registration store the account in `tab_sessions` in
   `backend/users_database/data.db`, keyed by browser-session ID and tab ID.
4. Requests authenticate using both values. Account roles and verification status
   are read from the users table; guest UUIDs are recorded as guest sessions.
5. Logout deletes only the current tab's login record, preserving the shared
   browser cookie and other tabs' sessions. Deleting an account revokes its logins.

The Next.js document, chat, and feedback proxies forward the cookie and tab ID to
Flask. User-specific responses bypass caches. Conversation memory is scoped to
the login, so different tabs cannot share the default conversation accidentally.

## Configuration and migration

- Set a stable, secret `FLASK_SECRET_KEY` in the backend environment to keep
  cookies valid across restarts and across server workers. The existing random
  development fallback invalidates cookies whenever the backend restarts.
- `AUTH_SESSION_TTL_SECONDS` controls login expiration (default: 28800, eight
  hours). Expired sessions require signing in again.
- Set `SESSION_COOKIE_SECURE=true` when serving over HTTPS.
- The SQLite table is created automatically. Existing accounts and document data
  are retained, but old account-bearing cookies require a fresh login.
- API clients must retain the bootstrap cookie and send a UUID `X-Tab-ID` when
  registering, logging in, or accessing authenticated endpoints. A tab ID or
  user UUID alone does not authenticate a request.

Tab-specific login does not partition the shared document retrieval collection;
document visibility and retrieval permissions are separate concerns.

Duplicate detection applies while the source app document is active. Navigating
away releases its claim; a copy made after that may initially reuse the saved ID.
If both app documents become active again, the one that cannot claim the ID gets
a new ID and must sign in.
