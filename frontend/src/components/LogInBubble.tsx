"use client";

import { useState, type SubmitEvent } from "react";

interface LogInInputProps {
  onSubmit: (info: LogInInfo) => Promise<void>;
}

interface LogInInfo {
  role: "Guest" | "Other";
  email: string;
  password: string;
}

export function LogInBubble({ onSubmit }: LogInInputProps) {
  const [isGuest, setIsGuest] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (info: LogInInfo) => {
    if (isSubmitting) return;
    setErrorMessage("");
    setIsSubmitting(true);
    try {
      await onSubmit(info);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;
    if (isGuest) {
      void submit({ email: "", password: "", role: "Guest" });
      return;
    }
    if (!email.trim()) {
      setErrorMessage("Please enter your email.");
      return;
    }
    if (!password.trim()) {
      setErrorMessage("Please enter a password.");
      return;
    }
    setErrorMessage("");
    void submit({ email: email.trim(), password: password, role: (isGuest ? "Guest" : "Other")});
  };

  const inputClassName = "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-[#2d3748] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200";

  return (
    <div className="mx-auto w-full max-w-md rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-5 py-6 shadow-sm sm:px-6">
      <form onSubmit={handleSubmit} aria-busy={isSubmitting} noValidate className="flex flex-col gap-4">
        
        {/* Log In Info Information */}
        { isGuest ? (
          <div className="flex flex-col gap-4">
            <p>If you continue as a guest, you will still be able to upload files and ask questions, but you will not be able to connect to other machines and files will be deleted after you sign out.</p>
            <button type="submit" disabled={isSubmitting} className="mt-1 w-full rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
                Continue as a Guest
            </button>
            <button type="button" disabled={isSubmitting} onClick={() => setIsGuest((previous) => !previous)}>
              Log In
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <label htmlFor="signup-email" className="mb-1.5 block text-sm font-medium text-[#2d3748]">Email</label>
              <input id="signup-email" name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClassName} />
            </div>
            <div className="relative">
              <label htmlFor="signup-password" className="mb-1.5 block text-sm font-medium text-[#2d3748]">Password</label>
              <input
                id="signup-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={`${inputClassName} pr-12`}
              />
              <button
                type="button"
                onClick={() => setShowPassword((previous) => !previous)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-controls="signup-password"
                className="absolute right-3 translate-y-1 rounded p-1 text-gray-500 hover:text-gray-700 focus-visible:outline-2 focus-visible:outline-blue-500"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  {showPassword ? (
                    <>
                      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12Z" />
                      <circle cx="12" cy="12" r="3" />
                    </>
                  ) : (
                    <>
                      <path d="M3 8c2 4 5 6 9 6s7-2 9-6" />
                      <path d="m4 10-2 3m6 0-1 4m5-3v4m4-5 1 4m3-7 2 3" />
                    </>
                  )}
                </svg>
              </button>
            </div>
            <button type="submit" disabled={isSubmitting} className="mt-1 w-full rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
              Log In
            </button>
            <button type="button" disabled={isSubmitting} onClick={() => setIsGuest((previous) => !previous)}>
              Continue as Guest
            </button>
          </div>
        )}
        {errorMessage && <p role="alert" className="text-sm text-red-600">{errorMessage}</p>}
        {isSubmitting && <p role="status" className="text-sm text-gray-500">Please wait...</p>}
      </form>
    </div>
  );
}
