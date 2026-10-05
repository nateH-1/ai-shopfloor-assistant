"use client";

import { useState, type SubmitEvent } from "react";

interface SignUpInputProps {
  onSubmit: (info: SignUpInfo) => void;
}

interface SignUpInfo {
  role: "Worker" | "Admin" | "Guest";
  email: string;
  password: string;
  organization: string;
}

export function SignUpBubble({ onSubmit }: SignUpInputProps) {
  const [role, setRole] = useState<SignUpInfo["role"]>("Worker");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organization, setOrganization] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const handleSubmit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (role == "Guest") {
      setErrorMessage("");
      onSubmit({ role, email: "", password: "", organization: ""});
      return
    }
    if (!email.trim()) {
      setErrorMessage("Please enter your email.");
      return;
    }
    if (!password.trim()) {
      setErrorMessage("Please enter a password.");
      return;
    }
    if (!organization.trim()) {
      setErrorMessage("Please enter your organization name.");
      return;
    }

    setErrorMessage("");
    onSubmit({ role, email: email.trim(), password, organization: organization.trim() });
  };

  const inputClassName = "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-[#2d3748] outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200";

  return (
    <div className="mx-auto w-full max-w-md rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-5 py-6 shadow-sm sm:px-6">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        <fieldset>
          <legend className="mb-3 text-lg font-semibold text-[#1a202c]">Sign up as:</legend>
          <div className="grid grid-cols-3 gap-2">
            {(["Worker", "Admin", "Guest"] as const).map((option) => (
              <label key={option} className="cursor-pointer">
                <input
                  type="radio"
                  name="role"
                  value={option}
                  checked={role === option}
                  onChange={() => setRole(option)}
                  className="peer sr-only"
                />
                <span className="block rounded-lg border-2 border-transparent px-3 py-2.5 text-center text-sm font-medium text-[#2d3748] transition-colors hover:bg-blue-50 peer-checked:border-blue-500 peer-checked:bg-blue-50 peer-checked:text-blue-700 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-blue-500">
                  {option}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {role == "Guest" ? (
          <div className="flex flex-col gap-4">
            <p>If you continue as a guest, you will still be able to upload files and ask questions, but you will not be able to connect to other machines and files will be deleted after you sign out.</p>
            <button type="submit" className="mt-1 w-full rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
                Continue as a guest
            </button>
          </div>
          
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <label htmlFor="signup-email" className="mb-1.5 block text-sm font-medium text-[#2d3748]">Email</label>
              <input id="signup-email" name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputClassName} />
            </div>
            <div>
              <label htmlFor="signup-password" className="mb-1.5 block text-sm font-medium text-[#2d3748]">Password</label>
              <input id="signup-password" name="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={inputClassName} />
            </div>
            <div>
              <label htmlFor="signup-organization" className="mb-1.5 block text-sm font-medium text-[#2d3748]">{role == "Worker" ? "Organization Code" : "Organization Name"}</label>
              <input id="signup-organization" name="organization" type="text" autoComplete="organization" required value={organization} onChange={(e) => setOrganization(e.target.value)} className={inputClassName} />
            </div>
            {errorMessage && <p role="alert" className="text-sm text-red-600">{errorMessage}</p>}
            <button type="submit" className="mt-1 w-full rounded-lg bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500">
              Sign Up as {role == "Worker" ? "a Worker" : "an Admin"}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
