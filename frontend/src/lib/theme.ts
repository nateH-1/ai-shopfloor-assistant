export type Theme = "light" | "dark" | "red";

export const THEME_STORAGE_KEY = "shopfloor.theme";
export const DARK_MODE_QUERY = "(prefers-color-scheme: dark)";

export function parseTheme(value: string | null): Theme | null {
  return value === "light" || value === "dark" || value === "red" ? value : null;
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
  document.documentElement.classList.toggle("red", theme === "red");
}

// Run before the page paints so a saved theme never flashes light first.
// Only fixed application constants are interpolated into this script.
export const themeInitializationScript = `
  (() => {
    let theme;
    try { theme = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)}); } catch {}
    if (theme !== "light" && theme !== "dark" && theme !== "red") {
      theme = window.matchMedia(${JSON.stringify(DARK_MODE_QUERY)}).matches ? "dark" : "light";
    }
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("red", theme === "red");
  })();
`;
