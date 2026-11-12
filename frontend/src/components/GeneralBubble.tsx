"use client";

import { useState } from "react";
import { logout } from "@/lib/authApi";
import ThemeToggle from "./ThemeToggle";
import { useTheme } from "./ThemeProvider";

export default function GeneralBubble() {
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState("");
  const { saveTheme } = useTheme();

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setError("");
    try {
      await saveTheme();
      await logout();
      window.location.replace("/login");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to log out. Please try again.");
      setLoggingOut(false);
    }
  }

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-8">
      <h2 className="text-lg font-semibold text-foreground">General</h2>
      <fieldset disabled={loggingOut} className="space-y-3">
        <h3 className="text-base font-semibold text-foreground">Color theme</h3>
        <ThemeToggle />
      </fieldset>
      <div className="space-y-3">
        <h3 className="text-base font-semibold text-foreground">Account</h3>
        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <button
          type="button"
          disabled={loggingOut}
          onClick={() => { void handleLogout(); }}
          className="self-start rounded-lg bg-red-button px-4 py-2 border-2 border-transparent dark:border-red-button-border text-sm font-medium text-red-button-text transition-colors hover:bg-red-button-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loggingOut ? "Logging out..." : "Log out"}
        </button>
      </div>
    </section>
  );
}
