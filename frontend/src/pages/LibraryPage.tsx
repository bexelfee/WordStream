import type { FormEvent, ChangeEvent } from 'react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

type DocumentSummary = {
  id: number
  title: string
  author?: string | null
  source_type: 'text' | 'pdf' | 'epub' | 'audio_transcript'
  word_count: number
  words_read: number
  percent_complete: number
  processing?: boolean
  transcription_error?: string | null
}

const API_BASE = '/api'

export function LibraryPage() {
  const [docs, setDocs] = useState<DocumentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pasteText, setPasteText] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingOriginalTitle, setEditingOriginalTitle] = useState<string>('')
  const [uploading, setUploading] = useState(false)
  const [config, setConfig] = useState<{ hf_token_configured?: boolean } | null>(null)
  const [hfBannerDismissed, setHfBannerDismissed] = useState(() =>
    localStorage.getItem('wordstream_hf_banner_dismissed') === '1'
  )
  const [showHfSteps, setShowHfSteps] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/documents`)
        if (!res.ok) throw new Error('Failed to load documents')
        const data = await res.json()
        setDocs(data)
      } catch (e: any) {
        setError(e.message ?? 'Error')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then((r) => r.ok ? r.json() : null)
      .then((c) => c && setConfig(c))
      .catch(() => {})
  }, [])

  const hasProcessing = docs.some((d) => d.processing === true)
  useEffect(() => {
    if (!hasProcessing) return
    const POLL_MS = 2000
    async function poll() {
      try {
        const res = await fetch(`${API_BASE}/documents`)
        if (!res.ok) return
        const data = await res.json()
        setDocs(data)
      } catch {
        // ignore
      }
    }
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => clearInterval(id)
  }, [hasProcessing])

  async function handleCreateText(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!pasteText.trim() || !pasteTitle.trim()) return
    const body = { title: pasteTitle, text: pasteText }
    const url =
      editingId === null
        ? `${API_BASE}/documents/text`
        : `${API_BASE}/documents/${editingId}/text`

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      alert('Failed to create document')
      return
    }
    const doc = await res.json()
    if (editingId === null) {
      navigate(`/read/${doc.id}`)
    } else {
      // Update list locally
      setDocs((prev) =>
        prev.map((d) => (d.id === doc.id ? { ...d, title: doc.title } : d)),
      )
      setEditingId(null)
      setEditingOriginalTitle('')
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('Delete this document?')) return
    const res = await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' })
    if (!res.ok && res.status !== 204) {
      alert('Failed to delete document')
      return
    }
    setDocs((prev) => prev.filter((d) => d.id !== id))
  }

  async function handleEdit(id: number) {
    const doc = docs.find((d) => d.id === id)
    if (!doc) return
    const res = await fetch(`${API_BASE}/documents/${id}/content`)
    if (!res.ok) {
      alert('Failed to load document content')
      return
    }
    const data = await res.json()
    setEditingId(id)
    setEditingOriginalTitle(doc.title)
    setPasteTitle(doc.title)
    setPasteText(data.text)
  }

  async function handleUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg || 'Upload failed')
      }
      const doc = await res.json()
      const summary = {
        ...doc,
        words_read: doc.words_read ?? 0,
        percent_complete: doc.percent_complete ?? 0,
      }
      setDocs((prev) => [summary, ...prev])
      if (doc.processing === true || doc.source_type === 'audio_transcript') {
        navigate('/', { replace: true })
      } else {
        navigate(`/read/${doc.id}`)
      }
    } catch (err: any) {
      setError(err.message ?? 'Upload error')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const showHfBanner =
    config && config.hf_token_configured === false && !hfBannerDismissed

  function dismissHfBanner() {
    localStorage.setItem('wordstream_hf_banner_dismissed', '1')
    setHfBannerDismissed(true)
  }

  return (
    <div className="app-root">
      <header className="app-header">
        <div className="logo">WordStream</div>
        <div className="header-actions">
          <label className="header-button">
            {uploading ? 'Uploading…' : 'Upload PDF / ePub / MP3'}
            <input
              type="file"
              accept=".pdf,.epub,.mp3"
              onChange={handleUpload}
              style={{ display: 'none' }}
            />
          </label>
        </div>
      </header>
      {showHfBanner && (
        <div className="library-hf-banner">
          <p>
            For faster and more reliable audio model downloads, set a Hugging Face token (higher rate limits).
          </p>
          <button
            type="button"
            className="library-hf-banner-toggle"
            onClick={() => setShowHfSteps((s) => !s)}
          >
            {showHfSteps ? 'Hide steps' : 'How to fix'}
          </button>
          {showHfSteps && (
            <div className="library-hf-steps">
              <ol>
                <li>Create a token at <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer">huggingface.co/settings/tokens</a> (read access is enough).</li>
                <li>Set it in your environment:
                  <ul>
                    <li><strong>Docker:</strong> Add to <code>docker-compose.yml</code>: <code>environment: - HF_TOKEN=your_token</code></li>
                    <li><strong>Local:</strong> Add <code>HF_TOKEN=your_token</code> to a <code>.env</code> file in the project root or export in your shell.</li>
                  </ul>
                </li>
                <li>Restart the app so the token is picked up.</li>
              </ol>
            </div>
          )}
          <button
            type="button"
            className="library-hf-banner-dismiss"
            onClick={dismissHfBanner}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
      <main className="library-main">
        <section className="library-list">
          <h1>Your Library</h1>
          {loading && <p>Loading…</p>}
          {error && <p className="error">{error}</p>}
          {!loading && !error && docs.length === 0 && <p>No documents yet.</p>}
          <ul>
            {docs.map((d) => (
              <li key={d.id} className="library-item">
                <div>
                  <div className="library-title">{d.title}</div>
                  {d.author && <div className="library-author">{d.author}</div>}
                </div>
                <div className="library-meta">
                  <div className="library-progress">
                    {d.processing ? (
                      <span className="library-transcribing">
                        <span className="library-transcribing-spinner" aria-hidden />
                        Transcribing…
                      </span>
                    ) : (
                      <>
                        <span>
                          {d.words_read} / {d.word_count} words
                        </span>
                        <span>{d.percent_complete.toFixed(0)}%</span>
                      </>
                    )}
                  </div>
                  {!d.processing && d.transcription_error && (
                    <div className="library-author">{d.transcription_error}</div>
                  )}
                  <button onClick={() => navigate(`/read/${d.id}`)}>Read</button>
                  <button className="library-delete" onClick={() => handleDelete(d.id)}>
                    Delete
                  </button>
                  {!d.processing && (
                    <button onClick={() => handleEdit(d.id)}>Edit</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="library-create">
          <h2>Paste Text</h2>
          {editingId !== null && (
            <p className="library-editing-label">
              Editing “{editingOriginalTitle}” (ID {editingId})
            </p>
          )}
          <form onSubmit={handleCreateText} className="paste-form">
            <input
              type="text"
              placeholder="Title"
              value={pasteTitle}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setPasteTitle(e.target.value)}
            />
            <textarea
              placeholder="Paste text here…"
              value={pasteText}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setPasteText(e.target.value)}
              rows={10}
            />
            <button type="submit">Create &amp; Read</button>
          </form>
        </section>
      </main>
    </div>
  )
}

