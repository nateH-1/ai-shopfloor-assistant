/**
 * Next.js Route Handler — POST /api/documents/upload
 * Proxies multipart/form-data to Flask POST /api/documents/upload
 */

import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/server/authHeaders";

const FLASK_URL = process.env.FLASK_URL ?? "http://localhost:5000";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();

    const upstream = await fetch(`${FLASK_URL}/api/documents/upload`, {
      method: "POST",
      headers: authHeaders(req),
      body: formData,
      cache: "no-store",
    });

    const data = await upstream.json();
    return NextResponse.json(data, {
      status: upstream.status, headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    console.error("[/api/documents/upload] upstream error:", err);
    return NextResponse.json(
      { success: false, message: "Failed to reach the Flask backend." },
      { status: 502 }
    );
  }
}

