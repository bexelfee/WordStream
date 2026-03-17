/**
 * RSVP-friendly tokenizer and ORP (optimal recognition position) helper.
 * Split on whitespace and strong punctuation; break very long hyphenated tokens.
 */
const LONG_HYPHEN_THRESHOLD = 12

export function tokenize(text: string): string[] {
  if (!text.trim()) return []
  const normalized = text.trim().replace(/\s+/g, ' ')
  const firstSplit = normalized.split(/\s+|[\u2014\u2013:;]+/).filter(Boolean)
  const result: string[] = []
  for (const token of firstSplit) {
    if (token.length > LONG_HYPHEN_THRESHOLD && token.includes('-')) {
      const parts = token.split('-').filter(Boolean)
      result.push(...parts)
    } else {
      result.push(token)
    }
  }
  return result
}

export function getOrpIndex(word: string): number {
  const len = word.length
  if (len <= 1) return 0
  if (len <= 5) return 1
  if (len <= 9) return 2
  return 3
}
