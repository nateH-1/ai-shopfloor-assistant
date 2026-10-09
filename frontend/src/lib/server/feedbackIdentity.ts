import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

const COOKIE = "manufacturing_feedback_browser";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function feedbackOwner(req: NextRequest): string | undefined {
  const value = req.cookies.get(COOKIE)?.value;
  return value && UUID.test(value) ? value : undefined;
}

export function newFeedbackOwner(): string {
  return randomUUID();
}

export function rememberFeedbackOwner(req: NextRequest, res: NextResponse, owner: string) {
  // Anonymous browser ownership, not a user account. JavaScript cannot read it.
  res.cookies.set(COOKIE, owner, {
    httpOnly: true,
    sameSite: "strict",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  res.headers.set("Cache-Control", "no-store");
}

export function hasForeignOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  return origin !== null && origin !== req.nextUrl.origin;
}
