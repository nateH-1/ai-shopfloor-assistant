const STORAGE_KEY = "shopfloor.tab_id";
const TAB_LOCK_PREFIX = "shopfloor.tab:";
const BROWSER_LOCK = "shopfloor.browser-session";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type TabSessionState = {
  tabId?: Promise<string>;
  browserReady?: Promise<void>;
};

export class TabSessionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TabSessionError";
  }
}

function tabState(): TabSessionState {
  if (typeof window === "undefined" || !navigator.locks || !crypto.randomUUID) {
    throw new TabSessionError("Tab sign-in requires a current browser using HTTPS or localhost.");
  }
  // Keep one claim per document, including during development hot reloads.
  const browserWindow = window as Window & { __shopfloorTabSession?: TabSessionState };
  return browserWindow.__shopfloorTabSession ??= {};
}

async function claimTabId(state: TabSessionState): Promise<string> {
  let saved: string | null;
  try {
    saved = sessionStorage.getItem(STORAGE_KEY);
  } catch {
    throw new TabSessionError("Allow session storage in your browser to sign in to this tab.");
  }
  let candidate = saved && UUID.test(saved) ? saved : crypto.randomUUID();

  while (true) {
    const id = candidate;
    const acquired = await new Promise<boolean>((resolve, reject) => {
      void navigator.locks.request(`${TAB_LOCK_PREFIX}${id}`, { ifAvailable: true }, (lock) => {
        if (!lock) {
          resolve(false);
          return;
        }
        try {
          sessionStorage.setItem(STORAGE_KEY, id);
        } catch {
          throw new TabSessionError("Allow session storage in your browser to sign in to this tab.");
        }
        // A copied tab initially inherits sessionStorage. Holding this lock lets
        // that copy detect the collision and select its own ID before any request.
        return new Promise<void>((release) => {
          window.addEventListener("pagehide", () => {
            state.tabId = undefined;
            state.browserReady = undefined;
            release();
          }, { once: true });
          resolve(true);
        });
      }).catch(reject);
    });
    if (acquired) return id;
    candidate = crypto.randomUUID();
  }
}

function getTabId(state: TabSessionState): Promise<string> {
  if (!state.tabId) {
    const claim: Promise<string> = claimTabId(state).catch((error) => {
      if (state.tabId === claim) state.tabId = undefined;
      throw error;
    });
    state.tabId = claim;
  }
  return state.tabId;
}

function requireActiveClaim(state: TabSessionState, claim: Promise<string>): void {
  if (state.tabId !== claim) {
    throw new TabSessionError("This tab's session changed while the request was waiting. Reload the page and try again.");
  }
}

async function ensureBrowserSession(state: TabSessionState, tabId: string, claim: Promise<string>): Promise<void> {
  if (!state.browserReady) {
    // Only the first request needs to set the shared HttpOnly cookie. Serialize
    // bootstraps across tabs so simultaneous first visits cannot replace it.
    const ready: Promise<void> = Promise.resolve(navigator.locks.request(BROWSER_LOCK, async () => {
      requireActiveClaim(state, claim);
      const response = await fetch("/users/session", {
        method: "POST",
        headers: { "X-Tab-ID": tabId },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        throw new TabSessionError("Unable to initialize this browser session. Please try again.");
      }
    })).catch((error) => {
      if (state.browserReady === ready) state.browserReady = undefined;
      throw error;
    });
    state.browserReady = ready;
  }
  await state.browserReady;
}

/** Send a same-origin API request using this tab's independent login. */
export async function tabFetch(
  input: string,
  init: RequestInit = {},
  { refreshBrowserSession = false }: { refreshBrowserSession?: boolean } = {},
): Promise<Response> {
  const state = tabState();
  if (new URL(input, window.location.href).origin !== window.location.origin) {
    throw new TabSessionError("Tab sign-in requests must use this app's same-origin API routes.");
  }
  // pagehide clears the claim so a back/forward-restored document reclaims its
  // ID here (or gets a new ID if another live tab now owns the copied value).
  const claim = getTabId(state);
  const tabId = await claim;
  requireActiveClaim(state, claim);
  // Sign-in must recover after a cleared cookie or restarted backend even if
  // client-side navigation kept this document's bootstrap promise alive.
  if (refreshBrowserSession) state.browserReady = undefined;
  await ensureBrowserSession(state, tabId, claim);
  // Never replay a waiting mutation under a newly claimed or copied tab ID.
  requireActiveClaim(state, claim);
  const headers = new Headers(init.headers);
  headers.set("X-Tab-ID", tabId);
  return fetch(input, { ...init, headers, credentials: "same-origin", cache: "no-store" });
}
