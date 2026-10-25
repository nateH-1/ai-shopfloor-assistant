"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AuthenticationRequiredError, get_verification_status } from "@/lib/authApi";

export default function AuthGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublicPage = pathname === "/" || pathname === "/login";
  const [checkedPath, setCheckedPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setCheckedPath(null);
    setError(null);
    if (isPublicPage) return;

    async function checkSession() {
      try {
        await get_verification_status();
        if (active) setCheckedPath(pathname);
      } catch (error) {
        if (!active) return;
        setCheckedPath(null);
        if (error instanceof AuthenticationRequiredError) {
          const next = window.location.pathname + window.location.search + window.location.hash;
          router.replace(`/login?next=${encodeURIComponent(next)}`);
        } else {
          setError(error instanceof Error ? error.message : "Unable to check your session.");
        }
      }
    }

    void checkSession();
    return () => { active = false; };
  }, [pathname, isPublicPage, router, attempt]);

  if (isPublicPage) return children;
  if (error) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-[#f3f4f6] p-6">
        <div className="w-full max-w-md space-y-4 rounded-2xl border border-gray-200 bg-white p-6 text-center shadow-sm">
          <p role="alert" className="text-sm text-red-700">{error}</p>
          <button type="button" onClick={() => { setError(null); setAttempt((value) => value + 1); }} className="rounded-lg bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100">
            Try again
          </button>
        </div>
      </main>
    );
  }
  if (checkedPath !== pathname) {
    return <p role="status" className="p-6 text-center text-sm text-gray-600">Checking your session...</p>;
  }
  return children;
}
