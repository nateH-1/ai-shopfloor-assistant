// ChatPage — shown when there are messages (Figma node 48-8)
// Scrollable chat area with welcome heading at top, messages in middle,
// sticky input at the bottom.

"use client";

import { useEffect, useRef } from "react";
import type { Message } from "@/lib/types";
import type { Feedback } from "@/lib/feedbackApi";
import { ChatBubble } from "./ChatBubble";
import ChatInput from "./ChatInput";

interface ChatPageProps {
  messages: Message[];
  onSend: (message: string) => void;
  onClarificationSelect?: (label: string) => void;
  onRewrite?: (message: Message, feedback: Feedback) => void;
  isLoading?: boolean;
}

export default function ChatPage({ messages, onSend, onClarificationSelect, onRewrite, isLoading }: ChatPageProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex flex-col flex-1 overflow-hidden" style={{ backgroundColor: "#f3f4f6" }}>
      {/* Scrollable message area */}
      <div className="flex-1 overflow-y-auto px-4 pt-10 pb-4">
        <div className="max-w-2xl mx-auto w-full">
          {/* Small welcome header stays at top of chat */}
          <div className="flex flex-col items-center mb-8">
            <div
              className="flex items-center justify-center w-14 h-14 rounded-full mb-4"
              style={{ background: "linear-gradient(135deg, #a855f7 0%, #3b82f6 100%)" }}
            >
              <BotIcon className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-[#1a202c] text-xl font-semibold mb-1 tracking-tight">
              Welcome to Kuldeep
            </h1>
            <p className="text-gray-500 text-sm text-center max-w-sm leading-relaxed">
              Your AI assistant for manufacturing processes, manuals, and SOPs. Ask me anything to get started.
            </p>
          </div>

          {/* Messages */}
          <div className="flex flex-col gap-4">
            {messages.map((msg, index) => (
              <ChatBubble
                key={msg.id}
                message={msg}
                onOptionSelect={onClarificationSelect ?? onSend}
                onRewrite={onRewrite}
                isLatest={index === messages.length - 1}
              />
            ))}

            {/* Typing indicator */}
            {isLoading && (
              <div className="flex items-start gap-3">
                <div
                  className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full"
                  style={{ background: "linear-gradient(135deg, #a855f7 0%, #3b82f6 100%)" }}
                >
                  <BotIcon className="w-5 h-5 text-white" />
                </div>
                <div
                  className="rounded-2xl rounded-tl-sm bg-white px-5 py-4 shadow-sm"
                  style={{ border: "1px solid #e5e7eb" }}
                >
                  <TypingDots />
                </div>
              </div>
            )}
          </div>

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Sticky input bar */}
      <div className="px-4 py-4" style={{ backgroundColor: "#f3f4f6" }}>
        <div className="max-w-2xl mx-auto w-full">
          <ChatInput onSend={onSend} disabled={isLoading} />
        </div>
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-gray-400"
          style={{
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }}
        />
      ))}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
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
