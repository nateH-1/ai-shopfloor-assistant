/**
 * Next.js Route Handler — POST /api/chat
 *
 * Acts as a server-side proxy to the Flask backend.
 * This keeps FLASK_URL out of the browser bundle and avoids CORS issues.
 *
 * ── Environment variables ────────────────────────────────────────────────────
 *   FLASK_URL   Full base URL of your Flask service.
 *              e.g.  http://localhost:5000   or   https://api.yourdomain.com
 *
 * ── Flask endpoint expected ──────────────────────────────────────────────────
 *   POST  {FLASK_URL}/chat
 *   Body: { message: string; history: {role, content}[]; session_id?: string }
 *   200:  { reply: string; session_id?: string; metadata?: { sources: Source[] } }
 */

import { NextRequest, NextResponse } from "next/server";
import { feedbackOwner, newFeedbackOwner, rememberFeedbackOwner, hasForeignOrigin } from "@/lib/server/feedbackIdentity";

const FLASK_URL = process.env.FLASK_URL ?? "http://localhost:5000";

export async function POST(req: NextRequest) {
  // Feedback endpoints use this same browser identity to keep anonymous votes
  // scoped to the browser that received the answer.
  if (hasForeignOrigin(req)) {
    return NextResponse.json({ error: "Cross-site chat requests are not allowed." }, { status: 403 });
  }
  const owner = feedbackOwner(req) ?? newFeedbackOwner();
  try {
    const body = await req.json();

    const upstream = await fetch(`${FLASK_URL}/chat`, {
      method: "POST",
      // The header is server-to-server; browser JavaScript never receives it.
      headers: { "Content-Type": "application/json", "X-Feedback-Owner": owner },
      body: JSON.stringify(body),
    });

    const data = await upstream.json();

    const response = NextResponse.json(data, { status: upstream.status });
    rememberFeedbackOwner(req, response, owner);
    return response;
  } catch (err) {
    console.error("[/api/chat] upstream error:", err);
    return NextResponse.json(
      { error: "Failed to reach the AI backend. Is the Flask server running on port 5000?" },
      { status: 502 }
    );
  }
}
