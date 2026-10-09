"use client";

import { useRouter } from "next/navigation";
import GenericHeader from "@/components/GenericHeader";
import { SignUpBubble } from "@/components/SignUpBubble";

export default function SignUpPage() {
  const router = useRouter();

  return (
    <div className="flex min-h-dvh flex-col bg-[#f3f4f6]">
      <GenericHeader />
      <main className="mx-auto grid w-full max-w-5xl flex-1 content-center items-center gap-8 px-4 py-10 md:grid-cols-2">
        <div className="text-center md:text-left">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-[#1a202c]">
            Welcome to Kuldeep
          </h1>
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-[#1a202c]">
            The AI Shopfloor Assistant
          </h1>
          <p className="text-sm leading-relaxed text-gray-500">
            Sign up to get started with your AI assistant. Upload documents and ask questions, without details going to the cloud.
          </p>
        </div>
        <SignUpBubble onSubmit={() => router.push("/chat")} />
      </main>
    </div>
  );
}
