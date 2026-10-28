"use client";

import { useState } from "react";
import { logout } from "@/lib/authApi";

export default function AccountBubble() {
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState("");

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setError("");
    try {
      await logout();
      window.location.replace("/login");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Failed to log out. Please try again.");
      setLoggingOut(false);
    }
  }

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-2xl border border-gray-200 bg-white p-5 shadow-sm sm:p-8">
      <h2 className="text-lg font-semibold text-[#1a202c]">Account</h2>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <button
        type="button"
        disabled={loggingOut}
        onClick={() => { void handleLogout(); }}
        className="self-start rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loggingOut ? "Logging out..." : "Log out"}
      </button>
    </section>
  );
}
