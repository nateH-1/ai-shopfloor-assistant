import { NextRequest, NextResponse } from "next/server";
import { hasForeignOrigin } from "@/lib/server/feedbackIdentity";

const FLASK_URL = process.env.FLASK_URL ?? "http://127.0.0.1:5000";
const MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024;

export async function POST(req: NextRequest) {
  try {
    if (hasForeignOrigin(req)) {
      return NextResponse.json(
        { error: "Cross-site transcription is not allowed." },
        { status: 403 }
      );
    }
    if (Number(req.headers.get("content-length")) > MAX_AUDIO_SIZE_BYTES + 65536) {
      return NextResponse.json({ error: "Audio file exceeds the 25 MB limit." }, { status: 413 });
    }

    const form = await req.formData();
    const audio = form.get("audio");

    if (!(audio instanceof File)) {
      return NextResponse.json(
        { error: "Missing audio file. Send multipart/form-data with an 'audio' field." },
        { status: 400 }
      );
    }

    if (audio.size === 0) {
      return NextResponse.json({ error: "Audio file is empty." }, { status: 400 });
    }

    if (audio.size > MAX_AUDIO_SIZE_BYTES) {
      return NextResponse.json(
        { error: `Audio file exceeds the 25 MB limit (received ${(audio.size / 1024 / 1024).toFixed(1)} MB).` },
        { status: 413 }
      );
    }

    const upstreamForm = new FormData();
    upstreamForm.append("audio", audio, audio.name || "recording.webm");

    // Local Flask inference only: no API key or cloud fallback.
    const upstream = await fetch(`${FLASK_URL}/api/transcribe`, {
      method: "POST",
      body: upstreamForm,
      cache: "no-store",
      signal: AbortSignal.timeout(120000),
    });

    const data = await upstream.json().catch(() => ({}));

    if (!upstream.ok) {
      const errorMessage =
        (typeof data.error === "string" ? data.error : data.error?.message) ||
        "Local transcription request failed.";
      return NextResponse.json({ error: errorMessage }, { status: upstream.status });
    }

    const text = (data as { text?: string }).text?.trim();
    if (!text) {
      return NextResponse.json(
        { error: "Transcription completed but no text was returned." },
        { status: 422 }
      );
    }

    return NextResponse.json({ text }, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    console.error("[/api/transcribe] error:", err);
    return NextResponse.json(
      { error: "The local speech service is unavailable or timed out. Check the backend and local speech model." },
      { status: 502 }
    );
  }
}
