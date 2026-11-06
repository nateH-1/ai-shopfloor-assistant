"use client";

import { useRouter } from "next/navigation";
import GenericHeader from "@/components/GenericHeader";
import { SignUpBubble } from "@/components/SignUpBubble";
import { authenticate } from "@/lib/authApi";
import { getAuthPagePath, getPostAuthPath } from "@/lib/authNavigation";

export default function SignUpPage() {
  const router = useRouter();

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <GenericHeader
        onLogIn={() => router.push(getAuthPagePath("/login"))}
        onSignUp={() => router.push(getAuthPagePath("/"))}
      />
      <main className="mx-auto grid w-full max-w-5xl flex-1 content-center items-center gap-8 px-4 py-10 md:grid-cols-2">
        <div className="text-center md:text-left">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-foreground">
            Welcome to Kuldeep
          </h1>
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-foreground">
            The AI Shopfloor Assistant
          </h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Sign up to get started with your AI assistant. Upload documents and ask questions, without details going to the cloud.
          </p>
        </div>
        <SignUpBubble onSubmit={async (info) => {
          await authenticate("register", info);
          router.replace(getPostAuthPath());
        }} />
      </main>
    </div>
  );
}