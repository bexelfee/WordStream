import { describe, it, expect } from 'vitest'
import { getOrpIndex, tokenize } from './wordUtils'

describe('tokenize', () => {
  it('returns empty array for empty or whitespace-only text', () => {
    expect(tokenize('')).toEqual([])
    expect(tokenize('   ')).toEqual([])
  })

  it('splits on spaces', () => {
    expect(tokenize('one two three')).toEqual(['one', 'two', 'three'])
  })

  it('splits on em-dash and strong punctuation', () => {
    expect(tokenize('one—two:three')).toEqual(['one', 'two', 'three'])
  })

  it('breaks long hyphenated tokens', () => {
    const long = 'character-creation—masterpieces'
    const words = tokenize(long)
    expect(words).toContain('character')
    expect(words).toContain('creation')
    expect(words.some((w) => w.length > 12 && w.includes('-'))).toBe(false)
  })
})

describe('getOrpIndex', () => {
  it('returns 0 for empty or single char', () => {
    expect(getOrpIndex('')).toBe(0)
    expect(getOrpIndex('a')).toBe(0)
  })
  it('returns 1 for short words (2–5 chars)', () => {
    expect(getOrpIndex('ab')).toBe(1)
    expect(getOrpIndex('five')).toBe(1)
  })
  it('returns 2 for medium words (6–9 chars)', () => {
    expect(getOrpIndex('sixchr')).toBe(2)
    expect(getOrpIndex('ninechars')).toBe(2)
  })
  it('returns 3 for longer words (10+ chars)', () => {
    expect(getOrpIndex('tencharsss')).toBe(3)
  })
})
