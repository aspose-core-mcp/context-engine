/** Tiny className joiner for the Mono kit (no runtime deps). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
