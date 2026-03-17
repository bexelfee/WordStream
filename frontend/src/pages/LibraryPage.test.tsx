import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LibraryPage } from './LibraryPage'

describe('LibraryPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/api/documents') && !url.includes('/content')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
      }
      if (url.includes('/api/config')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ hf_token_configured: false }) })
      }
      return Promise.reject(new Error('unmocked'))
    })
  })

  it('renders and shows Your Library once documents are loaded', async () => {
    render(
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>,
    )
    expect(screen.getByText(/Your Library/i)).toBeInTheDocument()
    await screen.findByText(/No documents yet|Upload PDF/)
    expect(screen.getByText(/Your Library/i)).toBeInTheDocument()
  })
})
