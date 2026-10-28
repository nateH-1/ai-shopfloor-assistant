// Chat bubble components for AI Assistant and User messages
// Matches Figma design:
//   AI bubble: white card with rounded corners, robot avatar on left, dark text
//   User bubble: light gray pill/rounded rectangle, right-aligned, no avatar

"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AnswerFeedback from "./AnswerFeedback";
import type { Feedback } from "@/lib/feedbackApi";
import type { Message, Source, Clarification } from "@/lib/types";

// ─── AI Assistant Bubble ────────────────────────────────────────────────────

export function AssistantBubble({
  content,
  sources,
  clarification,
  onOptionSelect,
  isLatest,
  feedbackId,
  feedbackUnavailable,
  onRewrite,
}: {
  content: string;
  sources?: Source[];
  clarification?: Clarification;
  onOptionSelect?: (value: string) => void;
  isLatest?: boolean;
  feedbackId?: string;
  feedbackUnavailable?: boolean;
  onRewrite?: (feedback: Feedback) => void;
}) {
  const [showSources, setShowSources] = useState(false);
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const hasSources = sources && sources.length > 0;
  const [fullSources, setFullSources] = useState<Set<number>>(new Set());

  return (
    <div className="flex items-start gap-3 w-full">
      {/* Avatar */}
      <div
        className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full"
        style={{ background: "linear-gradient(135deg, #a855f7 0%, #3b82f6 100%)" }}
      >
        <BotIcon className="w-5 h-5 text-white" />
      </div>

      {/* Bubble + sources */}
      <div className="flex flex-col gap-2 max-w-[75%]">
        <div
          className="rounded-2xl rounded-tl-sm bg-white px-5 py-4 shadow-sm self-start w-fit max-w-full overflow-hidden"
          style={{ border: "1px solid #e5e7eb" }}
        >
          <div className="prose prose-sm max-w-none text-[#2d3748] break-words
            prose-p:my-1 prose-p:leading-relaxed
            prose-ul:my-1 prose-ol:my-1
            prose-li:my-0.5 prose-li:leading-relaxed
            [&_ul]:list-disc [&_ol]:list-decimal
            [&_li::marker]:text-[#2d3748] [&_li::marker]:font-normal
            prose-strong:font-semibold prose-strong:text-[#1a202c]
            prose-headings:text-[#1a202c] prose-headings:font-semibold
            prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
            prose-blockquote:border-l-2 prose-blockquote:border-gray-300 prose-blockquote:text-gray-600 prose-blockquote:not-italic">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
          {clarification && onOptionSelect && (
            <div className="mt-3 flex flex-wrap gap-2">
              {clarification.options.map((opt) => {
                const isSelected = selectedOption === opt.value;
                const isDisabled = selectedOption !== null || !isLatest;
                return (
                  <button
                    key={opt.value}
                    disabled={isDisabled}
                    onClick={() => {
                      setSelectedOption(opt.value);
                      onOptionSelect(opt.value);
                    }}
                    className={[
                      "rounded-full border px-3 py-1.5 text-xs transition-colors",
                      isSelected
                        ? "border-purple-600 bg-purple-600 text-white"
                        : isDisabled
                        ? "border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed"
                        : "border-purple-300 text-purple-700 hover:bg-purple-50",
                    ].join(" ")}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Server-issued IDs exclude connection errors and clarification prompts. */}
        {/* The answer text is passed only for the browser's local read-aloud button. */}
        {feedbackId && <AnswerFeedback messageId={feedbackId} answerText={content} onRewrite={onRewrite} />}
        {feedbackUnavailable && <p className="text-xs text-gray-500">Feedback is temporarily unavailable for this answer.</p>}

        {/* Source toggle */}
        {hasSources && (
          <div>
            <button
              onClick={() => setShowSources((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-[#6b7280] hover:text-[#374151] transition-colors"
            >
              <BookIcon className="w-3.5 h-3.5" />
              {showSources ? "Hide" : "Show"} {sources.length} source
              {sources.length !== 1 ? "s" : ""}
              <ChevronIcon
                className={`w-3 h-3 transition-transform ${showSources ? "rotate-180" : ""}`}
              />
            </button>

            {showSources && (
              <div className="mt-2 flex flex-col gap-1.5">
                {sources.map((src) => {
                  const isExpanded = fullSources.has(src.id);
                  const snippet = isExpanded
                    ? src.full_snippet ?? src.snippet
                    : src.snippet;

                  return (
                    <button
                      key={src.id}
                      onClick={() => toggleFullSources(src.id)}
                      aria-expanded={isExpanded}
                      className="rounded-lg bg-white px-3 py-2 text-xs shadow-sm text-left"
                      style={{ border: "1px solid #e5e7eb" }}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <ChevronIcon className={`w-3 h-3 transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                        <span className="font-medium text-[#374151] truncate max-w-45" title={src.file}>
                          {src.file}
                        </span>
                        <span
                          className="shrink-0 rounded-full px-2 py-0.5 text-white text-[10px] font-semibold"
                          style={{ background: "linear-gradient(135deg, #a855f7 0%, #3b82f6 100%)" }}
                        >
                          p.{src.page}
                        </span>
                      </div>
                      <p
                        className={`text-[#6b7280] leading-snug ${isExpanded ? "whitespace-pre-wrap break-words" : "line-clamp-2"}`}
                        title={snippet}
                      >
                        {snippet}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
  function toggleFullSources(id: number) {
    setFullSources((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
    });
}
}

// ─── User Bubble ─────────────────────────────────────────────────────────────

export function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end w-full">
      <div
        className="rounded-2xl rounded-tr-sm px-5 py-3 max-w-[75%]"
        style={{ backgroundColor: "#e5e7eb" }}
      >
        <p className="text-[#374151] text-sm leading-relaxed">
          {content}
        </p>
      </div>
    </div>
  );
}

// ─── Generic ChatBubble dispatcher ──────────────────────────────────────────

export function ChatBubble({
  message,
  onOptionSelect,
  isLatest,
  onRewrite,
}: {
  message: Message;
  onOptionSelect?: (value: string) => void;
  isLatest?: boolean;
  onRewrite?: (message: Message, feedback: Feedback) => void;
}) {
  if (message.role === "assistant") {
    return <AssistantBubble feedbackId={message.feedbackId} feedbackUnavailable={message.feedbackUnavailable} content={message.content} sources={message.sources} clarification={message.clarification} onOptionSelect={onOptionSelect} isLatest={isLatest} onRewrite={onRewrite ? (feedback) => onRewrite(message, feedback) : undefined} />;
  }
  return <UserBubble content={message.content} />;
}

// ─── Icons ───────────────────────────────────────────────────────────────────

function BotIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
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

function BookIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  );
}

function ChevronIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

