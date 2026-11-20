const WORD = /[A-Za-z]+(?:'[A-Za-z]+)?/g;

function relevantSuggestion(word: string, item: unknown): item is string {
  if (typeof item !== "string") return false;
  const suggestion = item.trim();
  if (!suggestion || suggestion.toLowerCase() === word.toLowerCase()) return false;
  if (suggestion[0]?.toLowerCase() !== word[0]?.toLowerCase()) return false;
  return Math.abs(suggestion.length - word.length) <= 2;
}

export type SpellSpan = { start: number; end: number; suggestions?: string[] };

/** Ranges of words the English dictionary does not recognize. */
export function misspelledSpans(
  text: string,
  isWord: (word: string) => boolean,
  suggest: (word: string) => string[] = () => [],
): SpellSpan[] {
  const spans: SpellSpan[] = [];
  for (const match of text.matchAll(WORD)) {
    const word = match[0];
    if (word.replace(/'/g, "").length < 2) continue;
    if (isWord(word) || isWord(word.toLowerCase())) continue;
    const start = match.index ?? 0;
    const suggestions = word.length > 24 ? [] : suggest(word)
      .filter((item) => relevantSuggestion(word, item))
      .slice(0, 5);
    spans.push({ start, end: start + word.length, suggestions });
  }
  return spans;
}

/** Replace one misspelled range and leave every other character where it is. */
export function replaceMisspelling(
  text: string,
  start: number,
  end: number,
  replacement: string,
): { text: string; caret: number } | null {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end > text.length || start >= end) return null;
  if (!replacement) return null;
  return {
    text: text.slice(0, start) + replacement + text.slice(end),
    caret: start + replacement.length,
  };
}
