import type { AccountTheme } from "./themeApi";
import type { Theme } from "./theme";

/** Keep a Settings draft tied to the login that loaded it. */
export function createThemePreferences({ read, write, apply, fallback }: {
  read: () => Promise<AccountTheme>;
  write: (account: AccountTheme, theme: Theme) => Promise<void>;
  apply: (theme: Theme) => void;
  fallback: () => Theme;
}) {
  let account: AccountTheme | null = null;
  let selected: Theme | null = null;
  let dirty = false;
  let generation = 0;
  let loading: Promise<void> | null = null;
  let saving: Promise<void> | null = null;

  function load(): Promise<void> {
    if (account) return Promise.resolve();
    if (loading) return loading;
    const currentGeneration = generation;
    const request = read().then((result) => {
      if (generation !== currentGeneration) return;
      account = { ...result };
      selected = result.theme ?? fallback();
      // Adopt the current browser preference on the first Settings exit too.
      dirty = result.user_id !== null && result.theme === null;
      apply(selected);
    }).finally(() => {
      if (loading === request) loading = null;
    });
    loading = request;
    return request;
  }

  function select(theme: Theme) {
    selected = theme;
    dirty = account?.user_id != null && theme !== account.theme;
    apply(theme);
  }

  function save(): Promise<void> {
    if (saving) return saving;
    if (!account?.user_id || !dirty || selected === null) return Promise.resolve();
    const owner = account;
    const request = (async () => {
      // Serialize saves so an earlier selection cannot overwrite a later one.
      while (account === owner && dirty && selected !== null) {
        const next = selected;
        await write(owner, next);
        if (account !== owner) return;
        owner.theme = next;
        dirty = selected !== next;
      }
    })().finally(() => {
      if (saving === request) saving = null;
    });
    saving = request;
    return request;
  }

  function reset() {
    generation += 1;
    account = null;
    selected = null;
    dirty = false;
    loading = null;
    saving = null;
  }

  return { load, select, save, reset, hasAccount: () => account?.user_id != null };
}
