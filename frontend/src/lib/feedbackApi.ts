export type Vote = "helpful" | "not_helpful";
export type Feedback = {
  vote: Vote;
  reason: string;
  comment: string;
  updated_at: string;
};
export type FeedbackInput = Pick<Feedback, "vote" | "reason" | "comment">;

export async function requestFeedback(
  messageId: string,
  method: "GET" | "PUT" | "DELETE" = "GET",
  body?: FeedbackInput,
  signal?: AbortSignal,
): Promise<Feedback | null> {
  // All browser feedback calls go through Next.js, not directly to Flask.
  const response = await fetch(`/api/feedback/${encodeURIComponent(messageId)}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal: signal ?? AbortSignal.timeout(15000),
  });
  const data = await response.json();
  if (method === "GET" && response.status === 404) return null;
  if (!response.ok) throw new Error(data.error ?? "Feedback could not be saved.");
  return data.feedback;
}
