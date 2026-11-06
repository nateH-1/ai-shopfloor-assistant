"use client";

import { useState, useEffect, useCallback } from "react";
import { get_guest_status, enable_guest } from "@/lib/settingsAPI";

export default function GuestManagementBubble() {

  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingStatusChange, setIsLoadingStatusChange] = useState(false);
  const [error, setError] = useState("");
  const [guestEnabled, setGuestEnabled] = useState<boolean | null>(null);

  const getGuestStatus = useCallback(async () => {
    setIsLoading(true);
    try {
      const status = await get_guest_status();
      setError("");
      setGuestEnabled(status.guests_enabled);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load guest settings.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleEnable = async (status: "enabled" | "disabled") => {
    if (isLoadingStatusChange) return;
    setIsLoadingStatusChange(true);
    setError("");
    try {
      const result = await enable_guest(status);
      setGuestEnabled(result.guests_enabled);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update guest settings.");
    } finally {
      setIsLoadingStatusChange(false);
    }
  };

  useEffect(() => {
    void getGuestStatus();
  }, [getGuestStatus]);

  return (
    <section
      aria-label="Guest Management"
      className={`mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-8 `}>

      <h2 className="text-lg font-semibold text-foreground">Manage Guest Features</h2>
      <p className="text-sm leading-relaxed text-muted-foreground">
        If guest features are enabled, users will be able to use the application without creating an account.
        If enabled, Guests can upload their own documents and ask questions, but cannot share access to documents, and uploads are deleted after 24 hours.
        If disabled, users won't be able to continue as a Guest and current Guests will be logged out.
      </p>
      {isLoading ? (
        <p className="text-sm font-semibold text-foreground">
          Loading info...
        </p>
      ) : guestEnabled !== null ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-4">
        <p className="text-sm leading-relaxed text-foreground">
          Guest features are currently {guestEnabled ? "enabled" : "disabled"}
        </p>
        <button
          type="button"
          className="flex items-center justify-center gap-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50 px-3 py-3 text-sm font-medium text-blue-700 dark:text-blue-300 transition-colors hover:bg-blue-100 dark:hover:bg-blue-900/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isLoadingStatusChange}
          onClick={() => handleEnable(guestEnabled ? "disabled" : "enabled")}
        >
          {isLoadingStatusChange ? "Saving..." : guestEnabled ? "Disable guests" : "Enable guests"}
        </button>
      </div>
      ) : null}
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
    </section>
  );
}
