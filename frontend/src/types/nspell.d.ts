declare module "nspell" {
  interface SpellChecker {
    correct(word: string): boolean;
    suggest(word: string): string[];
    add(word: string): void;
  }

  export default function nspell(dictionary: { aff: Uint8Array; dic: Uint8Array }): SpellChecker;
}
