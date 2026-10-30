import { tabFetch } from "./tabSession";

/**
 * chatApi.ts — thin client that talks to the Next.js /api/chat proxy.
 *
 * The proxy (src/app/api/chat/route.ts) forwards requests to the Flask
 * backend, keeping FLASK_URL server-side and avoiding CORS issues.
 *
 * NEXT_PUBLIC_API_BASE_URL may specify a same-origin prefix. Authentication
 * uses the Next.js proxies so the browser cookie stays on this app's origin.
 */

import type { ChatRequest, ChatResponse, Message } from "./types";

/** Base URL for the Next.js API routes (proxy). */
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? ""; // empty = same origin

/**
 * Send a user message to the backend and return the assistant reply.
 *
 * @param message   The user's latest message text.
 * @param history   Conversation history to send for context.
 * @param sessionId Optional session/thread ID for stateful backends.
 */
export async function sendMessage(
  message: string,
  history: Pick<Message, "role" | "content">[] = [],
  sessionId?: string
): Promise<ChatResponse> {
  const body: ChatRequest = {
    message,
    history,
    ...(sessionId ? { session_id: sessionId } : {}),
  };

  const res = await tabFetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let message: string;
    try {
      const errData = await res.json();
      message = errData.error ?? `Server error ${res.status}`;
    } catch {
      message = await res.text().catch(() => `Server error ${res.status}`);
    }
    throw new Error(message);
  }

  return res.json() as Promise<ChatResponse>;
}

/**
 * Send a recorded audio blob to the server-side Whisper proxy and get text back.
 */
export async function transcribeAudio(
  audioBlob: Blob,
  filename = "recording.webm"
): Promise<string> {
  const formData = new FormData();
  formData.append("audio", audioBlob, filename);

  const res = await tabFetch(`${API_BASE}/api/transcribe`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    let message: string;
    try {
      const errData = await res.json();
      message = errData.error ?? `Transcription failed (${res.status})`;
    } catch {
      message = await res.text().catch(() => `Transcription failed (${res.status})`);
    }
    throw new Error(message);
  }

  const data = (await res.json()) as { text?: string };
  if (!data.text) {
    throw new Error("No transcription text returned.");
  }

  return data.text;
}
