/**
 * Next.js Route Handler — POST /api/chat/spelling
 *
 * Checks the draft against an English dictionary. The chat box draws a red
 * wavy line under words that are misspelled or not real words.
 */

import { NextRequest, NextResponse } from "next/server";
import dictionary from "dictionary-en";
import nspell from "nspell";
import { hasForeignOrigin } from "@/lib/server/feedbackIdentity";
import { misspelledSpans } from "@/lib/spellcheck";

const spell = nspell(dictionary);
spell.add("Kuldeep");

export async function POST(req: NextRequest) {
  if (hasForeignOrigin(req)) {
    return NextResponse.json({ error: "Cross-site chat requests are not allowed." }, { status: 403 });
  }
  try {
    const body = await req.json().catch(() => ({}));
    const text = typeof body?.text === "string" ? body.text.slice(0, 4000) : "";
    return NextResponse.json({
      spans: misspelledSpans(
        text,
        (word) => spell.correct(word),
        (word) => spell.suggest(word),
      ),
    });
  } catch (err) {
    console.error("[/api/chat/spelling] error:", err);
    return NextResponse.json({ spans: [] }, { status: 502 });
  }
}
