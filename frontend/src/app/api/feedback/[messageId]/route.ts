import { NextRequest, NextResponse } from "next/server";
import { feedbackOwner, hasForeignOrigin } from "@/lib/server/feedbackIdentity";

const FLASK_URL = process.env.FLASK_URL ?? "http://127.0.0.1:5000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
type Context = { params: Promise<{ messageId: string }> };

async function proxy(req: NextRequest, context: Context) {
  // This proxy keeps the browser identity cookie private from client code and
  // prevents a page from another origin from changing local feedback.
  if (hasForeignOrigin(req)) {
    return NextResponse.json({ error: "Cross-site feedback is not allowed." }, { status: 403 });
  }
  const owner = feedbackOwner(req);
  if (!owner) {
    return NextResponse.json({ error: "This browser cannot access that feedback. Start a new conversation." }, { status: 401 });
  }
  const { messageId } = await context.params;
  if (!UUID.test(messageId)) {
    return NextResponse.json({ error: "Answer not found." }, { status: 404 });
  }
  let body: string | undefined;
  if (req.method === "PUT") {
    // Check before forwarding so an oversized comment never reaches Flask.
    if (Number(req.headers.get("content-length")) > 16384) {
      return NextResponse.json({ error: "Feedback request is too large." }, { status: 413 });
    }
    body = await req.text();
    if (Buffer.byteLength(body, "utf8") > 16384) {
      return NextResponse.json({ error: "Feedback request is too large." }, { status: 413 });
    }
    try { JSON.parse(body); } catch {
      return NextResponse.json({ error: "Send valid JSON feedback." }, { status: 400 });
    }
  }
  try {
    // Only our HttpOnly cookie supplies ownership; ignore browser-supplied headers.
    const upstream = await fetch(`${FLASK_URL}/api/feedback/${messageId}`, {
      method: req.method,
      headers: { "Content-Type": "application/json", "X-Feedback-Owner": owner },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    return NextResponse.json(await upstream.json(), {
      status: upstream.status, headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "The feedback service is unavailable. Please try again." }, { status: 502 });
  }
}

export const GET = proxy;
export const PUT = proxy;
export const DELETE = proxy;
