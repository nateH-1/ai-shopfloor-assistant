"use client";

import { useRouter } from "next/navigation";
import GenericHeader from "@/components/GenericHeader";
import { SignUpBubble } from "@/components/SignUpBubble";

export default function SignUpPage() {
  const router = useRouter();

  return (
    <div className="flex min-h-dvh flex-col bg-[#f3f4f6]">
      <GenericHeader />
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-10">
        <div className="mb-8 text-center">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-[#1a202c]">
            Welcome to Kuldeep
          </h1>
          <p className="text-sm leading-relaxed text-gray-500">
            Sign up to get started with your AI manufacturing assistant.
          </p>
        </div>
        <SignUpBubble onSubmit={() => router.push("/chat")} />
      </main>
    </div>
  );
}
