import type { ChangeEvent } from 'react'
import { flushSync } from 'react-dom'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getOrpIndex, tokenize } from '../utils/wordUtils'

type Progress = {
  current_word_index: number
  word_count: number
}

type Chapter = {
  id: number
  title: string
  start_word_index: number
}

type Page = {
  id: number
  page_number: number
  start_word_index: number
}

const API_BASE = '/api'

/** Save reading progress at most this often (seconds). Configurable in UI; guard against 0. */
const PROGRESS_SAVE_INTERVAL_SECONDS_DEFAULT = 10
const PROGRESS_SAVE_INTERVAL_MIN_SECONDS = 1

// Total characters to show in the context strip (excluding the current word)
const CONTEXT_CHAR_BUDGET = 100
// Only re-center the strip when offset would change by more than this (reduces jitter at high WPM)
const CONTEXT_SCROLL_THRESHOLD_PX = 14

export function ReaderPage() {
  const { documentId } = useParams()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [index, setIndex] = useState(0)
  const [wpm, setWpm] = useState(300)
  const [playing, setPlaying] = useState(false)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapterId, setSelectedChapterId] = useState<number | ''>('')
  const [pages, setPages] = useState<Page[]>([])
  const [contextOffsetPx, setContextOffsetPx] = useState(0)
  const [showContextStrip, setShowContextStrip] = useState(true)
  const [transcribing, setTranscribing] = useState(false)
  const [transcribingError, setTranscribingError] = useState<string | null>(null)
  const [progressSaveIntervalSeconds, setProgressSaveIntervalSeconds] = useState(
    () => Math.max(PROGRESS_SAVE_INTERVAL_MIN_SECONDS, Number(localStorage.getItem('wordstream_progress_save_interval_sec')) || PROGRESS_SAVE_INTERVAL_SECONDS_DEFAULT)
  )
  const currentIndexRef = useRef(0)
  const lastSavedIndexRef = useRef<number | null>(null)
  const lastSaveTimeRef = useRef<number>(0)
  const contextViewportRef = useRef<HTMLDivElement>(null)
  const contextSliderRef = useRef<HTMLDivElement>(null)
  const contextCurrentRef = useRef<HTMLSpanElement>(null)

  const words = useMemo(() => tokenize(text), [text])

  const currentChapter = useMemo(() => {
    if (chapters.length === 0) return null
    const beforeOrAt = chapters.filter((c) => c.start_word_index <= index)
    if (beforeOrAt.length === 0) return null
    const sorted = beforeOrAt.sort((a, b) => b.start_word_index - a.start_word_index)
    return sorted[0] ?? null
  }, [chapters, index])

  useEffect(() => {
    if (!currentChapter) {
      setSelectedChapterId('')
      return
    }
    const selectedChapter = chapters.find((c) => c.id === selectedChapterId)
    const selectedStart = selectedChapter?.start_word_index ?? null
    const currentStart = currentChapter.start_word_index
    if (selectedStart !== currentStart) {
      setSelectedChapterId(currentChapter.id)
    }
  }, [currentChapter, chapters, selectedChapterId])

  function getCurrentChapterRange() {
    if (!currentChapter) return null
    const idx = chapters.findIndex((c) => c.id === currentChapter.id)
    if (idx === -1) return null
    const start = currentChapter.start_word_index
    const next = idx < chapters.length - 1 ? chapters[idx + 1] : null
    const end = next ? next.start_word_index : words.length
    if (end <= start) return null
    return { start, end, nextStart: next ? next.start_word_index : null as number | null }
  }

  const contextChars = useMemo(() => {
    const current = words[index] ?? ''
    if (!current) {
      return { left: '', current: '', right: '' }
    }

    const halfBudget = Math.floor(CONTEXT_CHAR_BUDGET / 2)

    // Build left side up to halfBudget chars
    const leftWords: string[] = []
    let leftLen = 0
    for (let i = index - 1; i >= 0; i--) {
      const w = words[i]
      const extra = (leftLen === 0 ? 0 : 1) + w.length
      if (leftLen + extra > halfBudget) break
      leftWords.push(w)
      leftLen += extra
    }
    leftWords.reverse()

    // Build right side up to halfBudget chars
    const rightWords: string[] = []
    let rightLen = 0
    for (let i = index + 1; i < words.length; i++) {
      const w = words[i]
      const extra = (rightLen === 0 ? 0 : 1) + w.length
      if (rightLen + extra > halfBudget) break
      rightWords.push(w)
      rightLen += extra
    }

    const left = leftWords.join(' ')
    const right = rightWords.join(' ')
    return { left, current, right }
  }, [words, index])

  useLayoutEffect(() => {
    const viewport = contextViewportRef.current
    const slider = contextSliderRef.current
    const currentSpan = contextCurrentRef.current
    if (!viewport || !slider || !currentSpan) return

    const raf = requestAnimationFrame(() => {
      const vw = viewport.offsetWidth
      const sw = slider.offsetWidth
      const left = currentSpan.offsetLeft
      const cw = currentSpan.offsetWidth
      let target = vw / 2 - (left + cw / 2)
      const minOffset = vw - sw
      const maxOffset = 0
      target = Math.max(minOffset, Math.min(maxOffset, target))

      setContextOffsetPx((prev) => {
        if (Math.abs(target - prev) <= CONTEXT_SCROLL_THRESHOLD_PX) return prev
        return target
      })
    })
    return () => cancelAnimationFrame(raf)
  }, [contextChars])

  useEffect(() => {
    if (!documentId) return

    async function load() {
      const [contentRes, progressRes, structureRes] = await Promise.all([
        fetch(`${API_BASE}/documents/${documentId}/content`),
        fetch(`${API_BASE}/documents/${documentId}/progress`),
        fetch(`${API_BASE}/documents/${documentId}/structure`),
      ])
      if (!contentRes.ok || !progressRes.ok || !structureRes.ok) {
        navigate('/')
        return
      }
      const content = await contentRes.json()
      const prog = await progressRes.json()
      const structure = await structureRes.json()

      if (content.processing === true) {
        setTranscribing(true)
        setTranscribingError(content.processing_error ?? null)
        return
      }
      setTranscribing(false)
      setTranscribingError(content.processing_error ?? null)
      setText(content.text)
      setProgress(prog)
      setIndex(prog.current_word_index ?? 0)
      setChapters(structure.chapters ?? [])
      setPages(structure.pages ?? [])
    }

    load()
  }, [documentId, navigate])

  useEffect(() => {
    if (!documentId || !transcribing) return

    const POLL_INTERVAL_MS = 3000
    const id = setInterval(async () => {
      const [contentRes, progressRes, structureRes] = await Promise.all([
        fetch(`${API_BASE}/documents/${documentId}/content`),
        fetch(`${API_BASE}/documents/${documentId}/progress`),
        fetch(`${API_BASE}/documents/${documentId}/structure`),
      ])
      if (!contentRes.ok || !progressRes.ok || !structureRes.ok) return
      const content = await contentRes.json()
      if (content.processing === true) return
      const prog = await progressRes.json()
      const structure = await structureRes.json()
      setTranscribing(false)
      setTranscribingError(content.processing_error ?? null)
      setText(content.text)
      setProgress(prog)
      setIndex(prog.current_word_index ?? 0)
      setChapters(structure.chapters ?? [])
      setPages(structure.pages ?? [])
    }, POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [documentId, transcribing])

  useEffect(() => {
    if (!playing || words.length === 0) return
    const intervalMs = 60000 / wpm
    const id = window.setInterval(() => {
      setIndex((prev) => {
        const lastIndex = Math.max(words.length - 1, 0)
        const range = getCurrentChapterRange()
        let next = prev + 1

        if (range) {
          if (range.nextStart !== null && next >= range.end) {
            next = range.nextStart
          }
        }

        if (next >= lastIndex) {
          next = lastIndex
          if (playing) {
            setPlaying(false)
          }
        }

        return next
      })
    }, intervalMs)
    return () => window.clearInterval(id)
  }, [playing, wpm, words.length])

  const effectiveSaveIntervalSec = Math.max(PROGRESS_SAVE_INTERVAL_MIN_SECONDS, progressSaveIntervalSeconds || PROGRESS_SAVE_INTERVAL_SECONDS_DEFAULT)

  useEffect(() => {
    currentIndexRef.current = index
  }, [index])

  useEffect(() => {
    if (progress) {
      lastSavedIndexRef.current = progress.current_word_index
      lastSaveTimeRef.current = Date.now()
      currentIndexRef.current = progress.current_word_index
    }
  }, [progress])

  useEffect(() => {
    if (!progress || !documentId) return
    const saveProgress = (wordIndex: number) => {
      lastSavedIndexRef.current = wordIndex
      lastSaveTimeRef.current = Date.now()
      fetch(`${API_BASE}/documents/${documentId}/progress`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_word_index: wordIndex }),
      }).catch(() => {})
    }
    const intervalMs = 1000
    const id = setInterval(() => {
      const now = Date.now()
      const elapsedSec = (now - lastSaveTimeRef.current) / 1000
      const latestIndex = currentIndexRef.current
      if (elapsedSec >= effectiveSaveIntervalSec && lastSavedIndexRef.current !== latestIndex) {
        saveProgress(latestIndex)
      }
    }, intervalMs)
    return () => {
      clearInterval(id)
      const latestIndex = currentIndexRef.current
      if (lastSavedIndexRef.current !== latestIndex) {
        saveProgress(latestIndex)
      }
    }
  }, [documentId, progress, effectiveSaveIntervalSec])

  const handleProgressSaveIntervalChange = (e: ChangeEvent<HTMLInputElement>) => {
    const raw = Number(e.target.value)
    const sec = Number.isFinite(raw) ? Math.max(PROGRESS_SAVE_INTERVAL_MIN_SECONDS, raw) : PROGRESS_SAVE_INTERVAL_SECONDS_DEFAULT
    setProgressSaveIntervalSeconds(sec)
    localStorage.setItem('wordstream_progress_save_interval_sec', String(sec))
  }

  const currentWord = words[index] ?? ''
  const orpIndex = getOrpIndex(currentWord)

  const before = currentWord.slice(0, orpIndex)
  const focal = currentWord.charAt(orpIndex)
  const after = currentWord.slice(orpIndex + 1)

  const wordsRead = words.length > 0 ? Math.min(words.length, index + 1) : 0
  const chapterRange = getCurrentChapterRange()
  const percent = (() => {
    if (words.length === 0) return 0
    if (!chapterRange) {
      return (wordsRead / words.length) * 100
    }
    const clampedIndex = Math.min(
      Math.max(index, chapterRange.start),
      chapterRange.end - 1,
    )
    const wordsInChapter = Math.max(chapterRange.end - chapterRange.start, 1)
    const wordsReadInChapter = clampedIndex - chapterRange.start + 1
    return (wordsReadInChapter / wordsInChapter) * 100
  })()

  function jump(delta: number) {
    setIndex((prev: number) => {
      const next = Math.min(Math.max(prev + delta, 0), Math.max(words.length - 1, 0))
      return next
    })
  }

  function onScrubChange(e: ChangeEvent<HTMLInputElement>) {
    const value = Number(e.target.value)
    if (!Number.isFinite(value) || words.length === 0) return
    const range = getCurrentChapterRange()
    if (range) {
      const span = Math.max(range.end - range.start - 1, 0)
      const offset = span > 0 ? Math.round((value / 100) * span) : 0
      const idx = range.start + offset
      setIndex(Math.max(range.start, Math.min(idx, range.end - 1)))
    } else {
      const idx = Math.round((value / 100) * (words.length - 1))
      setIndex(idx)
    }
  }

  function jumpToChapter(startIndex: number) {
    const safeMax = Math.max(words.length - 1, 0)
    const idx = Math.max(0, Math.min(startIndex, safeMax))
    flushSync(() => setIndex(idx))
  }

  function jumpToPage(startIndex: number) {
    setIndex(Math.max(0, Math.min(startIndex, Math.max(words.length - 1, 0))))
  }

  if (transcribing) {
    return (
      <div className="app-root">
        <header className="app-header">
          <button className="header-button" onClick={() => navigate('/')}>
            ← Library
          </button>
          <div className="logo">WordStream</div>
          <div />
        </header>
        <main className="reader-main">
          <p className="reader-message">Transcribing your audiobook… This may take a few minutes.</p>
          {transcribingError && <p className="reader-message">{transcribingError}</p>}
        </main>
      </div>
    )
  }

  return (
    <div className="app-root">
      <header className="app-header">
        <button className="header-button" onClick={() => navigate('/')}>
          ← Library
        </button>
        <div className="logo">WordStream</div>
        <div />
      </header>
      <main className="reader-main">
        <section className="reader-card">
          <div className="reader-anchor">
            <div className="reader-anchor-arrow reader-anchor-arrow-top" />
            <div className="reader-anchor-line" />
            <div className="reader-anchor-arrow reader-anchor-arrow-bottom" />
          </div>
          <div className="reader-word">
            <span className="reader-word-before">{before}</span>
            <span className="reader-word-orp">{focal}</span>
            <span className="reader-word-after">{after}</span>
          </div>
        </section>
        {words.length > 0 && (
          <div className="reader-context-area">
            {showContextStrip ? (
              <div
                ref={contextViewportRef}
                className="reader-context-viewport reader-context-clickable"
                aria-hidden
                onClick={() => setShowContextStrip(false)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setShowContextStrip(false)
                  }
                }}
                role="button"
                tabIndex={0}
                title="Hide context text"
              >
                <div
                  ref={contextSliderRef}
                  className="reader-context-slider"
                  style={{ transform: `translateX(${contextOffsetPx}px)` }}
                >
                  <span className="reader-context-fade">… </span>
                  {contextChars.left && (
                    <span className="reader-context-word">
                      {contextChars.left}{' '}
                    </span>
                  )}
                  <span ref={contextCurrentRef} className="reader-context-current">
                    {contextChars.current}
                  </span>
                  {contextChars.right && (
                    <span className="reader-context-word">
                      {' '}{contextChars.right}
                    </span>
                  )}
                  <span className="reader-context-fade"> …</span>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="reader-context-show-btn"
                onClick={() => setShowContextStrip(true)}
              >
                Show text
              </button>
            )}
          </div>
        )}
        {(currentChapter || (selectedChapterId && chapters.find((c) => c.id === selectedChapterId))) && (
          <div className="reader-chapter-label">
            {(() => {
              const selectedCh = selectedChapterId ? chapters.find((c) => c.id === selectedChapterId) : null
              if (selectedCh && currentChapter && selectedCh.start_word_index === currentChapter.start_word_index) {
                return selectedCh.title
              }
              return currentChapter?.title ?? selectedCh?.title ?? ''
            })()}
          </div>
        )}
        <section className="reader-controls">
          <div className="reader-controls-row">
            <button onClick={() => setIndex(0)}>|&laquo;</button>
            <button onClick={() => jump(-10)}>&laquo;</button>
            <button onClick={() => setPlaying((p) => !p)}>
              <span aria-hidden="true">{playing ? '❚❚' : '▶'}</span>
            </button>
            <button onClick={() => jump(10)}>&raquo;</button>
          </div>
          <div className="reader-scrubber-row">
            <input
              type="range"
              min={0}
              max={100}
              value={percent}
              onChange={onScrubChange}
            />
            <div className="reader-scrubber-meta">
              <span>
                Word {wordsRead} of {words.length}
              </span>
              <span>{percent.toFixed(0)}%</span>
            </div>
          </div>
          <div className="reader-speed-row">
            <span>Speed</span>
            <input
              type="range"
              min={100}
              max={1000}
              step={10}
              value={wpm}
              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                setWpm(Number(e.target.value))
              }
            />
            <span>{wpm} WPM</span>
          </div>
          <div className="reader-speed-row">
            <label htmlFor="progress-save-interval">Save progress every</label>
            <input
              id="progress-save-interval"
              type="number"
              min={PROGRESS_SAVE_INTERVAL_MIN_SECONDS}
              max={300}
              value={progressSaveIntervalSeconds}
              onChange={handleProgressSaveIntervalChange}
            />
            <span>sec</span>
          </div>
          {(chapters.length > 0 || pages.length > 0) && (
            <div className="reader-structure-row">
              {chapters.length > 0 && (
                <select
                  value={selectedChapterId}
                  onChange={(e) => {
                    const rawValue = e.target.value
                    const id = Number(rawValue)
                    const ch = chapters.find((c) => c.id === id)
                    if (ch) {
                      setSelectedChapterId(ch.id)
                      jumpToChapter(ch.start_word_index)
                    }
                  }}
                >
                  <option value="" disabled>
                    Jump to chapter…
                  </option>
                  {chapters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </select>
              )}
              {pages.length > 0 && (
                <select
                  onChange={(e) => {
                    const val = Number(e.target.value)
                    if (!Number.isNaN(val)) jumpToPage(val)
                  }}
                  defaultValue=""
                >
                  <option value="" disabled>
                    Jump to page…
                  </option>
                  {pages.map((p) => (
                    <option key={p.id} value={p.start_word_index}>
                      Page {p.page_number}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

