// WelcomePage — shown when there are no messages yet (Figma node 49-223)
// Centered robot avatar + heading + subtitle + floating input box

"use client";

import ChatInput from "./ChatInput";

interface WelcomePageProps {
  onSend: (message: string) => void;
}

export default function WelcomePage({ onSend }: WelcomePageProps) {
  return (
    <div className="flex flex-col flex-1 items-center justify-between bg-background">
      {/* Hero section */}
      <div className="flex flex-col items-center pt-16 pb-8 px-4">
        {/* Custom icon avatar */}
        <img src="/icon.png" alt="Kuldeep icon" className="w-16 h-16 object-contain mb-5" />

        {/* Heading */}
        <h1 className="text-foreground text-2xl font-semibold mb-2 tracking-tight">
          Welcome to Kuldeep
        </h1>

        {/* Subtitle */}
        <p className="text-muted-foreground text-sm text-center max-w-sm leading-relaxed">
          Your AI assistant for manufacturing processes, manuals, and SOPs. Ask me anything to get started.
        </p>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Input box — floating, centered, wide */}
      <div className="w-full max-w-2xl px-4 pb-12">
        <ChatInput onSend={onSend} />
      </div>
    </div>
  );
}

function BotIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="11" y="1" width="2" height="3" rx="1" />
      <circle cx="12" cy="1.5" r="1.5" />
      <rect x="4" y="4" width="16" height="12" rx="3" />
      <circle cx="9" cy="9" r="1.5" opacity="0.35" />
      <circle cx="15" cy="9" r="1.5" opacity="0.35" />
      <circle cx="9" cy="9" r="0.75" fill="white" />
      <circle cx="15" cy="9" r="0.75" fill="white" />
      <rect x="8" y="12" width="8" height="1.5" rx="0.75" fill="white" opacity="0.7" />
      <rect x="7" y="16" width="10" height="6" rx="2" />
      <rect x="2" y="17" width="4" height="4" rx="2" />
      <rect x="18" y="17" width="4" height="4" rx="2" />
    </svg>
  );
}
