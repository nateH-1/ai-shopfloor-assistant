export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "shopfloor.theme";
export const DARK_MODE_QUERY = "(prefers-color-scheme: dark)";

export function parseTheme(value: string | null): Theme | null {
  return value === "light" || value === "dark" ? value : null;
}

export function readStoredTheme(): Theme | null {
  try {
    return parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    // Browsers can block storage; the system preference still works.
    return null;
  }
}

export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

// Run before the page paints so a saved dark theme never flashes light first.
// Only fixed application constants are interpolated into this script.
export const themeInitializationScript = `
  (() => {
    let theme;
    try { theme = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)}); } catch {}
    const dark = theme === "dark" ||
      (theme !== "light" && window.matchMedia(${JSON.stringify(DARK_MODE_QUERY)}).matches);
    document.documentElement.classList.toggle("dark", dark);
  })();
`;
