"use client";

import { useEffect, useId, useRef, useState } from "react";
import { requestFeedback, type Feedback, type Vote } from "@/lib/feedbackApi";

const REASONS = [
  ["incorrect", "Incorrect information"],
  ["incomplete", "Incomplete answer"],
  ["irrelevant", "Didn't answer my question"],
  ["unclear", "Unclear explanation"],
  ["missing_sources", "Missing sources"],
  ["other", "Other"],
];

export default function AnswerFeedback({
  messageId,
  answerText,
  onRewrite,
}: {
  messageId: string;
  answerText: string;
  onRewrite?: (feedback: Feedback) => void;
}) {
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [draftVote, setDraftVote] = useState<Vote | "">("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // Browser-only read-aloud state. It is independent from saved answer feedback.
  const [isReading, setIsReading] = useState(false);
  const inFlight = useRef(false);
  const formId = useId();

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    let active = true;
    requestFeedback(messageId, "GET", undefined, controller.signal)
      .then((saved) => {
        if (!active) return;
        setFeedback(saved);
        setDraftVote(saved?.vote ?? "");
        setReason(saved?.reason ?? "");
        setComment(saved?.comment ?? "");
        setDetailsOpen(Boolean(saved?.reason || saved?.comment));
      })
      .catch(() => {
        if (active) setError("Couldn't load saved feedback. You can still try saving again.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [messageId]);

  useEffect(() => {
    // Stop the operating system voice when this answer bubble is removed.
    return () => {
      window.speechSynthesis?.cancel();
    };
  }, []);

  function toggleReadAloud() {
    // SpeechSynthesis uses the voice installed in the user's browser/OS; it
    // does not call Flask, OpenAI, or an external text-to-speech service.
    if (!("speechSynthesis" in window)) {
      setError("Read aloud is not supported by this browser.");
      return;
    }
    if (isReading) {
      window.speechSynthesis.cancel();
      setIsReading(false);
      setNotice("Read aloud stopped.");
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(toSpeechText(answerText));
    utterance.onend = () => setIsReading(false);
    utterance.onerror = () => {
      setIsReading(false);
      setError("The answer could not be read aloud.");
    };
    setError("");
    setNotice("Reading answer aloud.");
    setIsReading(true);
    window.speechSynthesis.speak(utterance);
  }

  function selectVote(vote: Vote) {
    setDraftVote(vote);
    setNotice("");
    setError("");
    if (vote === "helpful") {
      setReason("");
    } else {
      setDetailsOpen(true);
    }
  }

  async function save(): Promise<Feedback | null> {
    if (!draftVote || inFlight.current) return null;
    inFlight.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await requestFeedback(messageId, "PUT", {
        vote: draftVote,
        reason: draftVote === "not_helpful" ? reason : "",
        comment,
      });
      setFeedback(saved);
      setDraftVote(saved?.vote ?? "");
      setReason(saved?.reason ?? "");
      setComment(saved?.comment ?? "");
      setNotice(
        saved?.vote === "not_helpful"
          ? "Feedback saved. You can rewrite this answer now."
          : "Feedback saved."
      );
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save feedback. Please try again.");
      return null;
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  async function rewrite() {
    if (!onRewrite || !draftVote || inFlight.current) return;
    const current = hasChanges || !feedback ? await save() : feedback;
    if (current?.vote === "not_helpful") {
      onRewrite(current);
    }
  }

  async function remove() {
    if (inFlight.current) return;
    inFlight.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await requestFeedback(messageId, "DELETE");
      setFeedback(null);
      setDraftVote("");
      setReason("");
      setComment("");
      setDetailsOpen(false);
      setNotice("Feedback removed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove feedback.");
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }

  const disabled = loading || saving;
  const hasChanges = draftVote !== (feedback?.vote ?? "")
    || reason !== (feedback?.reason ?? "")
    || comment !== (feedback?.comment ?? "");
  const showDetails = Boolean(draftVote || feedback);

  return (
    <section
      aria-label="Answer feedback"
      className="mt-2 w-fit max-w-xl text-xs text-gray-700"
    >
      <div className="flex items-center gap-1 rounded-full border border-gray-200 bg-white p-1 shadow-sm">
        <button
          type="button"
          disabled={disabled}
          aria-pressed={draftVote === "helpful"}
          onClick={() => selectVote("helpful")}
          className={ratingClass(draftVote === "helpful")}
          title="Helpful"
        >
          <ThumbIcon selected={draftVote === "helpful"} />
          <span className="sr-only">Helpful</span>
        </button>
        <button
          type="button"
          disabled={disabled}
          aria-pressed={draftVote === "not_helpful"}
          onClick={() => selectVote("not_helpful")}
          className={ratingClass(draftVote === "not_helpful")}
          title="Not helpful"
        >
          <ThumbIcon down selected={draftVote === "not_helpful"} />
          <span className="sr-only">Not helpful</span>
        </button>
        {/* Read-aloud is intentionally separate from voting and never saves feedback. */}
        <button
          type="button"
          aria-pressed={isReading}
          onClick={toggleReadAloud}
          className={ratingClass(isReading)}
          title={isReading ? "Stop reading" : "Read answer aloud"}
        >
          <SpeakerIcon active={isReading} />
          <span className="sr-only">{isReading ? "Stop reading" : "Read answer aloud"}</span>
        </button>
      </div>

      {showDetails && (
        <form
          className="mt-2 w-[min(32rem,calc(100vw-3rem))] space-y-3 rounded-xl border border-gray-200 bg-white/95 p-3 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div>
            <p className="font-medium text-gray-900">
              {draftVote === "helpful" ? "Helpful feedback" : "Improve this answer"}
            </p>
            <p className="mt-0.5 text-gray-500">
              {draftVote === "helpful"
                ? "Save this rating for this answer."
                : "Add what went wrong, then save or rewrite the answer."}
            </p>
          </div>

          {draftVote === "not_helpful" && (
            <div>
              <label htmlFor={formId + "-reason"} className="mb-1 block font-medium text-gray-700">
                What could be better?
              </label>
              <select
                id={formId + "-reason"}
                value={reason}
                disabled={saving}
                onChange={(event) => setReason(event.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-100"
              >
                <option value="">Select a reason</option>
                {REASONS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
          )}

          <button
            type="button"
            disabled={disabled}
            onClick={() => setDetailsOpen((open) => !open)}
            className="font-medium text-purple-700 underline underline-offset-2 disabled:opacity-50"
          >
            {detailsOpen ? "Hide comment" : "Add a comment"}
          </button>

          {detailsOpen && (
            <div>
              <label htmlFor={formId + "-comment"} className="mb-1 block font-medium text-gray-700">
                Comment
              </label>
              <textarea
                id={formId + "-comment"}
                value={comment}
                maxLength={2000}
                disabled={saving}
                rows={3}
                onChange={(event) => setComment(event.target.value)}
                aria-describedby={formId + "-count"}
                placeholder="Example: too vague, missing the source, or too much detail."
                className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-100"
              />
              <p id={formId + "-count"} className="mt-1 text-gray-500">{comment.length}/2000 characters</p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={disabled || !draftVote || (!hasChanges && Boolean(feedback))}
              className="rounded-lg bg-purple-700 px-4 py-2 font-medium text-white shadow-sm hover:bg-purple-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving..." : feedback ? "Save changes" : "Save feedback"}
            </button>
            {feedback && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => void remove()}
                className="rounded-lg border border-gray-300 px-3 py-2 font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Remove
              </button>
            )}
            {feedback?.vote === "not_helpful" && onRewrite && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => void rewrite()}
                className="rounded-lg border border-purple-200 bg-purple-50 px-3 py-2 font-medium text-purple-800 hover:bg-purple-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {hasChanges ? "Save and rewrite" : "Rewrite now"}
              </button>
            )}
            <p role="status" aria-live="polite" className="min-h-4 text-gray-500">
              {loading ? "Loading feedback..." : notice}
            </p>
          </div>

          {error && <p role="alert" className="text-red-700">{error}</p>}
        </form>
      )}
    </section>
  );
}

function ratingClass(selected: boolean) {
  return [
    "inline-flex h-8 w-8 items-center justify-center rounded-full transition-colors disabled:opacity-50",
    selected
      ? "bg-purple-100 text-purple-800"
      : "text-gray-500 hover:bg-gray-100 hover:text-gray-800",
  ].join(" ");
}

function ThumbIcon({ down = false, selected = false }: { down?: boolean; selected?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill={selected ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${down ? "rotate-180" : ""}`}
    >
      <path d="M7 10v11H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3Z" />
      <path d="M7 10l4-8a3 3 0 0 1 3 3v4h5a3 3 0 0 1 3 3.5l-1.2 6A3 3 0 0 1 18 21H7" />
    </svg>
  );
}

function SpeakerIcon({ active }: { active: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 10v4h4l5 4V6l-5 4H4Z" />
      <path d="M16 9a4 4 0 0 1 0 6" />
      {active && <path d="M19 6a8 8 0 0 1 0 12" />}
    </svg>
  );
}

function toSpeechText(text: string) {
  // Answers are rendered from Markdown. Remove common visual-only Markdown so
  // the system voice reads the answer's words rather than punctuation symbols.
  return text
    .replace(/```[\s\S]*?```/g, "code example omitted")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[>#*_~]/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}
