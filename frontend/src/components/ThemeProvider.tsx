"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { applyTheme, DARK_MODE_QUERY, parseTheme, readStoredTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";
import { getThemePreference, saveThemePreference } from "@/lib/themeApi";
import { createThemePreferences } from "@/lib/themePreferences";

const ThemeContext = createContext<{
  theme: Theme | null;
  setTheme: (theme: Theme) => void;
  loadAccountTheme: () => Promise<void>;
  resetAccountTheme: () => void;
  saveTheme: () => Promise<void>;
} | null>(null);

export default function ThemeProvider({ children }: { children: ReactNode }) {
  // A stable initial render keeps server and client markup in sync.
  const [theme, setCurrentTheme] = useState<Theme | null>(null);
  const preference = useRef<Theme | null>(null);
  const accountGeneration = useRef(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [preferences] = useState(() => createThemePreferences({
    read: getThemePreference,
    write: saveThemePreference,
    fallback: () => readStoredTheme() ?? (window.matchMedia(DARK_MODE_QUERY).matches ? "dark" : "light"),
    apply: (next) => {
      preference.current = next;
      applyTheme(next);
      setCurrentTheme(next);
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // Account preferences still work when local storage is unavailable.
      }
    },
  }));

  const loadAccountTheme = useCallback(() => preferences.load(), [preferences]);
  const resetAccountTheme = useCallback(() => {
    accountGeneration.current += 1;
    preferences.reset();
    setSaveError(null);
  }, [preferences]);
  const saveTheme = useCallback(async () => {
    const generation = accountGeneration.current;
    setSaveError(null);
    try {
      await preferences.save();
    } catch (error) {
      if (generation === accountGeneration.current) {
        setSaveError(error instanceof Error ? error.message : "Unable to save your theme. Please try again.");
      }
      throw error;
    }
  }, [preferences]);

  useEffect(() => {
    const systemTheme = window.matchMedia(DARK_MODE_QUERY);
    preference.current = readStoredTheme();

    const syncTheme = () => {
      const next = preference.current ?? (systemTheme.matches ? "dark" : "light");
      applyTheme(next);
      setCurrentTheme(next);
    };
    const onStorage = (event: StorageEvent) => {
      // Other tabs can be signed in to different accounts.
      if (preferences.hasAccount()) return;
      if (event.key === THEME_STORAGE_KEY || event.key === null) {
        preference.current = parseTheme(event.newValue);
        syncTheme();
      }
    };

    syncTheme();
    systemTheme.addEventListener("change", syncTheme);
    window.addEventListener("storage", onStorage);
    return () => {
      systemTheme.removeEventListener("change", syncTheme);
      window.removeEventListener("storage", onStorage);
    };
  }, [preferences]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme: preferences.select, loadAccountTheme, resetAccountTheme, saveTheme }}>
      {children}
      {saveError && (
        <div role="alert" className="fixed bottom-4 left-4 right-4 z-50 mx-auto flex max-w-xl items-center gap-4 rounded-lg border border-border bg-card p-4 text-sm text-foreground shadow-lg">
          <p className="flex-1">{saveError}</p>
          <button type="button" onClick={() => { void saveTheme().catch(() => {}); }} className="rounded-lg bg-blue-button px-3 py-2 text-blue-button-text hover:bg-blue-button-hover">
            Retry
          </button>
        </div>
      )}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
