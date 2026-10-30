/**
 * Next.js Route Handler — GET /api/documents
 * Proxies to Flask GET /api/documents
 */

import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/server/authHeaders";

const FLASK_URL = process.env.FLASK_URL ?? "http://localhost:5000";

export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${FLASK_URL}/api/documents`, {
      headers: authHeaders(req),
      cache: "no-store",
    });
    const data = await upstream.json();
    return NextResponse.json(data, {
      status: upstream.status, headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    console.error("[/api/documents] upstream error:", err);
    return NextResponse.json(
      { error: "Failed to reach the Flask backend." },
      { status: 502 }
    );
  }
}

