"use client";

import { useTheme } from "./ThemeProvider";

const themeOptions = [
  { value: "light", label: "Light", borderClassName: "border-white" },
  { value: "dark", label: "Dark", borderClassName: "border-black" },
  { value: "red", label: "Red", borderClassName: "border-red-500" },
] as const;

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div role="group" aria-label="Color theme" className="flex flex-wrap gap-3">
      {themeOptions.map(({ value: option, label, borderClassName }) => (
        <button
          key={option}
          type="button"
          onClick={() => setTheme(option)}
          disabled={theme === null}
          aria-pressed={theme === option}
          className={`flex items-center justify-center gap-2 rounded-lg border-2 px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-button-focus disabled:cursor-not-allowed disabled:opacity-50 ${borderClassName} ${theme === option ? "bg-blue-button text-blue-button-text hover:bg-blue-button-hover" : "bg-muted text-foreground hover:bg-accent"}`}
        >
          {label}
          <svg aria-hidden="true" className={`h-4 w-4 ${theme === option ? "opacity-100" : "opacity-0"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 12 4 4L19 6" />
          </svg>
        </button>
      ))}
    </div>
  );
}
