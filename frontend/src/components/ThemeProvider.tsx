"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { applyTheme, DARK_MODE_QUERY, parseTheme, readStoredTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

const ThemeContext = createContext<{
  theme: Theme | null;
  toggleTheme: () => void;
} | null>(null);

export default function ThemeProvider({ children }: { children: ReactNode }) {
  // A stable initial render keeps server and client markup in sync.
  const [theme, setTheme] = useState<Theme | null>(null);
  const preference = useRef<Theme | null>(null);

  useEffect(() => {
    const systemTheme = window.matchMedia(DARK_MODE_QUERY);
    preference.current = readStoredTheme();

    const syncTheme = () => {
      const next = preference.current ?? (systemTheme.matches ? "dark" : "light");
      applyTheme(next);
      setTheme(next);
    };
    const onStorage = (event: StorageEvent) => {
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
  }, []);

  function toggleTheme() {
    const next = document.documentElement.classList.contains("dark") ? "light" : "dark";
    preference.current = next;
    applyTheme(next);
    setTheme(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Keep the toggle usable even when this browser disallows persistence.
    }
  }

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
