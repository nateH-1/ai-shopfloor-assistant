export type SpellSpan = { start: number; end: number; suggestions?: string[] };
export type SpellPiece = { text: string; misspelled: boolean };

/** Split draft text so only the reported ranges can be underlined. */
export function spellPieces(text: string, spans: SpellSpan[]): SpellPiece[] {
  const sorted = spans
    .filter((span) =>
      Number.isInteger(span.start) &&
      Number.isInteger(span.end) &&
      span.start >= 0 &&
      span.end > span.start &&
      span.start < text.length)
    .sort((left, right) => left.start - right.start);

  const pieces: SpellPiece[] = [];
  let cursor = 0;
  for (const span of sorted) {
    const start = Math.max(span.start, cursor);
    const end = Math.min(span.end, text.length);
    if (start >= end) continue;
    if (start > cursor) pieces.push({ text: text.slice(cursor, start), misspelled: false });
    pieces.push({ text: text.slice(start, end), misspelled: true });
    cursor = end;
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor), misspelled: false });
  if (pieces.length === 0) pieces.push({ text, misspelled: false });
  return pieces;
}

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** HTML for the same characters, with misspelled ranges wrapped. The text is not rewritten. */
export function highlightedHtml(text: string, spans: SpellSpan[]): string {
  if (!text) return "";
  let cursor = 0;
  return spellPieces(text, spans).map((piece) => {
    const start = cursor;
    cursor += piece.text.length;
    const safe = escapeHtml(piece.text);
    if (!piece.misspelled) return safe;
    return `<span class="misspelled-word" data-start="${start}" data-end="${start + piece.text.length}">${safe}</span>`;
  }).join("");
}
