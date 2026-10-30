/**
 * Next.js Route Handler — DELETE /api/documents/[filename]
 * Proxies to Flask DELETE /api/documents/<filename>
 *
 * maxDuration is set to 120s because deleting a document triggers a full
 * FAISS index rebuild which can take 20-60 seconds for large knowledge bases.
 */

import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/server/authHeaders";

export const maxDuration = 120;

const FLASK_URL = process.env.FLASK_URL ?? "http://localhost:5000";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ filename: string }> }
) {
  try {
    const { filename } = await params;
    const encoded = encodeURIComponent(filename);

    const upstream = await fetch(`${FLASK_URL}/api/documents/${encoded}`, {
      method: "DELETE",
      headers: authHeaders(req),
      cache: "no-store",
      signal: AbortSignal.timeout(115_000),
    });

    const contentType = upstream.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      return NextResponse.json(
        { success: false, message: "Unexpected response from Flask." },
        { status: 502 }
      );
    }

    const data = await upstream.json();
    return NextResponse.json(data, {
      status: upstream.status, headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    console.error("[/api/documents/[filename]] upstream error:", err);
    return NextResponse.json(
      { success: false, message: "Failed to reach the Flask backend. The server may still be rebuilding the index — please wait a moment and refresh." },
      { status: 502 }
    );
  }
}

