from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Iterable, Tuple
import tempfile
import threading

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import SessionLocal
from .models import Document, DocumentChapter, DocumentContent, DocumentPage, DocumentProgress

from pypdf import PdfReader
from ebooklib import epub
import re


settings = get_settings()
logger = logging.getLogger(__name__)


def _normalize_whitespace(text: str) -> str:
    # Collapse whitespace to single spaces, strip leading/trailing
    return " ".join(text.split())


# Match frontend: split on whitespace and strong punctuation; break long hyphenated tokens
LONG_HYPHEN_THRESHOLD = 12
_SPLIT_PATTERN = re.compile(r"\s+|\u2014|\u2013|[:;]+")


def _tokenize_words(text: str) -> list[str]:
    if not text:
        return []
    normalized = _normalize_whitespace(text)
    parts = _SPLIT_PATTERN.split(normalized)
    result: list[str] = []
    for token in parts:
        if not token:
            continue
        if len(token) > LONG_HYPHEN_THRESHOLD and "-" in token:
            result.extend(p for p in token.split("-") if p)
        else:
            result.append(token)
    return result


def _norm(t: str) -> str:
    """Normalize for chapter title matching: uppercase, strip punctuation."""
    return t.upper().rstrip(".,;:\u2014\u2013")


def _find_title_in_words(item_words: list[str], title_tokens: list[str]) -> int | None:
    """Return the index in item_words where title_tokens first appear, or None."""
    if not title_tokens:
        return 0
    n = len(title_tokens)
    for i in range(len(item_words) - n + 1):
        if all(
            _norm(item_words[i + j]) == _norm(title_tokens[j]) for j in range(n)
        ):
            return i
    return None


def _ensure_data_dir() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = settings.data_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


def _ensure_audio_dir() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = settings.data_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


_whisper_lock = threading.Lock()


@lru_cache(maxsize=1)
def _get_whisper_model():
    from faster_whisper import WhisperModel

    return WhisperModel("base", device="cpu", compute_type="int8")


def _transcribe_audio_sync(
    audio_path: Path, transcript_path: Path, language: str = "en"
) -> tuple[str, int]:
    """Run faster-whisper transcription. Returns (normalized_text, word_count)."""
    model = _get_whisper_model()
    with _whisper_lock:
        segments, _ = model.transcribe(str(audio_path), language=language or None)
    full_text = " ".join(s.text for s in segments if s.text).strip()
    normalized = _normalize_whitespace(full_text)
    words = _tokenize_words(normalized)
    return normalized, len(words)


async def create_audio_document(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    original_file_name: str,
    title: str | None,
    author: str | None,
) -> Document:
    docs_dir = _ensure_data_dir()
    audio_dir = _ensure_audio_dir()

    base_title = title or Path(original_file_name).stem or original_file_name
    filesize_bytes = len(file_bytes)

    doc = Document(
        title=base_title,
        author=author,
        source_type="audio_transcript",
        original_file_name=original_file_name,
        filesize_bytes=filesize_bytes,
        language="en",
        processing=True,
        transcription_error=None,
    )
    db.add(doc)
    await db.flush()

    audio_path = audio_dir / f"{doc.id}.mp3"
    audio_path.write_bytes(file_bytes)

    transcript_path = docs_dir / f"audio_{doc.id}_transcript.txt"
    transcript_path.write_text("", encoding="utf-8")

    content = DocumentContent(
        document_id=doc.id, content_path=str(transcript_path), word_count=0
    )
    progress = DocumentProgress(
        document_id=doc.id, current_word_index=0, last_opened_at=None
    )
    db.add_all([content, progress])
    await db.commit()
    await db.refresh(doc)
    return doc


async def run_transcription_for_document(document_id: int) -> None:
    """Background task: transcribe audio for document_id and update content + processing."""
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if not doc or not getattr(doc, "processing", False):
            return
        content = await db.get(DocumentContent, document_id)
        if not content:
            return
        audio_path = settings.data_dir / "audio" / f"{document_id}.mp3"
        if not audio_path.exists():
            doc.processing = False
            doc.transcription_error = "Audio file missing"
            await db.commit()
            return
        try:
            transcript_text, word_count = await asyncio.to_thread(
                _transcribe_audio_sync,
                audio_path,
                Path(content.content_path),
                doc.language or "en",
            )
        except Exception:
            logger.exception("Audio transcription failed", extra={"document_id": document_id})
            doc.processing = False
            doc.transcription_error = "Transcription failed"
            await db.commit()
            return
        Path(content.content_path).write_text(transcript_text, encoding="utf-8")
        content.word_count = word_count
        doc.processing = False
        doc.transcription_error = None
        await db.commit()


async def recover_incomplete_transcriptions() -> list[int]:
    """
    Recover or retry audio documents that were left processing during restarts.
    Returns document IDs that should be retried.
    """
    retry_ids: list[int] = []
    stale_before = datetime.utcnow() - timedelta(minutes=settings.transcription_stale_minutes)
    async with SessionLocal() as db:
        stmt = select(Document).where(
            Document.source_type == "audio_transcript",
            Document.processing == True,  # noqa: E712
        )
        docs = (await db.execute(stmt)).scalars().all()
        for doc in docs:
            content = await db.get(DocumentContent, doc.id)
            audio_path = settings.data_dir / "audio" / f"{doc.id}.mp3"
            transcript_path = Path(content.content_path) if content else None
            if not audio_path.exists():
                doc.processing = False
                doc.transcription_error = "Audio file missing"
                continue
            if not transcript_path or not transcript_path.exists():
                doc.processing = False
                doc.transcription_error = "Transcript file missing"
                continue
            # Retry if this looks stale; otherwise allow in-flight jobs to continue.
            if doc.updated_at is None or doc.updated_at <= stale_before:
                retry_ids.append(doc.id)
        await db.commit()
    return retry_ids


async def create_text_document(
    db: AsyncSession, *, title: str, author: str | None, text: str
) -> Document:
    normalized = _normalize_whitespace(text)
    words = _tokenize_words(normalized)
    word_count = len(words)

    docs_dir = _ensure_data_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    file_name = f"text_{timestamp}.txt"
    content_path = docs_dir / file_name
    content_path.write_text(normalized, encoding="utf-8")

    filesize_bytes = content_path.stat().st_size

    doc = Document(
        title=title,
        author=author,
        source_type="text",
        original_file_name=None,
        filesize_bytes=filesize_bytes,
        language="en",
    )
    db.add(doc)
    await db.flush()

    content = DocumentContent(
        document_id=doc.id, content_path=str(content_path), word_count=word_count
    )
    progress = DocumentProgress(
        document_id=doc.id, current_word_index=0, last_opened_at=None
    )
    db.add_all([content, progress])
    await db.commit()
    await db.refresh(doc)
    return doc


async def update_text_document(
    db: AsyncSession, *, document_id: int, title: str | None, text: str | None
) -> Document:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    _, content = await get_document_with_content(db, document_id)
    content_path = Path(content.content_path)

    if text is not None:
        normalized = _normalize_whitespace(text)
        words = _tokenize_words(normalized)
        word_count = len(words)
        content_path.write_text(normalized, encoding="utf-8")
        content.word_count = word_count
    if title is not None:
        doc.title = title

    await db.commit()
    await db.refresh(doc)
    return doc


async def create_pdf_document(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    original_file_name: str,
    title: str | None,
    author: str | None,
) -> Document:
    docs_dir = _ensure_data_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    text_file_name = f"pdf_{timestamp}.txt"
    text_path = docs_dir / text_file_name

    reader = PdfReader(BytesIO(file_bytes))
    all_words: list[str] = []
    pages_meta: list[Tuple[int, int]] = []  # (page_number, start_word_index)

    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        normalized = _normalize_whitespace(raw)
        page_words = _tokenize_words(normalized)
        start_index = len(all_words)
        pages_meta.append((idx, start_index))
        all_words.extend(page_words)

    normalized_full = " ".join(all_words)
    text_path.write_text(normalized_full, encoding="utf-8")
    filesize_bytes = len(file_bytes)

    doc = Document(
        title=title or original_file_name,
        author=author,
        source_type="pdf",
        original_file_name=original_file_name,
        filesize_bytes=filesize_bytes,
        language="en",
    )
    db.add(doc)
    await db.flush()

    content = DocumentContent(
        document_id=doc.id, content_path=str(text_path), word_count=len(all_words)
    )
    progress = DocumentProgress(
        document_id=doc.id, current_word_index=0, last_opened_at=None
    )
    db.add_all([content, progress])

    # Pages
    for page_number, start_word_index in pages_meta:
        db.add(
            DocumentPage(
                document_id=doc.id,
                page_number=page_number,
                start_word_index=start_word_index,
            )
        )

    # Chapters from outline (best-effort)
    try:
        outline = reader.outline
    except Exception:
        outline = []

    def _flatten_outline(items):
        for it in items:
            if isinstance(it, list):
                yield from _flatten_outline(it)
            else:
                yield it

    try:
        from pypdf.generic import Destination  # type: ignore
    except Exception:  # pragma: no cover
        Destination = object  # fall-back

    if outline:
        for item in _flatten_outline(outline):
            try:
                if isinstance(item, Destination):
                    title_text = str(item.title)
                    page_index = reader.get_destination_page_number(item)
                else:
                    # Some pypdf versions store dict-like outline entries
                    title_text = str(getattr(item, "title", None) or "")
                    dest = getattr(item, "destination", None)
                    if dest is None:
                        continue
                    page_index = reader.get_destination_page_number(dest)
                if not title_text:
                    continue
                # page_index is 0-based, our pages_meta is 1-based
                if 0 <= page_index < len(pages_meta):
                    _, start_word_index = pages_meta[page_index]
                    db.add(
                        DocumentChapter(
                            document_id=doc.id,
                            title=title_text,
                            start_word_index=start_word_index,
                        )
                    )
            except Exception:
                continue

    await db.commit()
    await db.refresh(doc)
    return doc


def _strip_html(raw: str) -> str:
    # Simple tag stripper for ePub XHTML content
    return re.sub(r"<[^>]+>", " ", raw)


async def create_epub_document(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    original_file_name: str,
    title: str | None,
    author: str | None,
) -> Document:
    docs_dir = _ensure_data_dir()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    text_file_name = f"epub_{timestamp}.txt"
    text_path = docs_dir / text_file_name

    # ebooklib.read_epub does not support fileobj in this version, so write to a temp file.
    with tempfile.NamedTemporaryFile(suffix=".epub") as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        book = epub.read_epub(tmp.name)

    spine_ids = [item[0] for item in book.spine]
    all_words: list[str] = []

    # Map item id to cumulative start index and per-item words (for chapter-in-file resolution)
    item_start_index: dict[str, int] = {}
    item_words: dict[str, list[str]] = {}

    for spine_id in spine_ids:
        item = book.get_item_with_id(spine_id)
        if item is None:
            continue
        raw_html = item.get_content().decode("utf-8", errors="ignore")
        text = _normalize_whitespace(_strip_html(raw_html))
        words = _tokenize_words(text)
        if not words:
            continue
        item_start_index[spine_id] = len(all_words)
        item_words[spine_id] = words
        all_words.extend(words)

    normalized_full = " ".join(all_words)
    text_path.write_text(normalized_full, encoding="utf-8")
    filesize_bytes = len(file_bytes)

    doc = Document(
        title=title or (book.title if getattr(book, "title", None) else original_file_name),
        author=author,
        source_type="epub",
        original_file_name=original_file_name,
        filesize_bytes=filesize_bytes,
        language="en",
    )
    db.add(doc)
    await db.flush()

    content = DocumentContent(
        document_id=doc.id, content_path=str(text_path), word_count=len(all_words)
    )
    progress = DocumentProgress(
        document_id=doc.id, current_word_index=0, last_opened_at=None
    )
    db.add_all([content, progress])

    # Chapters from TOC (best-effort)
    toc = getattr(book, "toc", [])

    def _flatten_toc(items):
        for it in items:
            # ebooklib TOC entries can be (Link, children) tuples
            if isinstance(it, tuple) and len(it) == 2:
                node, children = it
                yield node
                yield from _flatten_toc(children)
            else:
                yield it

    for node in _flatten_toc(toc):
        href = getattr(node, "href", None)
        title_text = str(getattr(node, "title", None) or "")
        if not href or not title_text:
            continue
        # href is something like 'chapter1.xhtml#frag'; strip fragment
        href_id = href.split("#", 1)[0]
        # ebooklib maps ids differently; best-effort match by ending
        matched_id = None
        for spine_id in spine_ids:
            item = book.get_item_with_id(spine_id)
            if item is None:
                continue
            if item.get_name().endswith(href_id):
                matched_id = spine_id
                break
        if matched_id is None or matched_id not in item_start_index:
            continue
        base = item_start_index[matched_id]
        # Resolve chapter start within the item so multiple TOC entries in one file get distinct indices
        title_tokens = _tokenize_words(title_text)
        iw = item_words.get(matched_id, [])
        offset = _find_title_in_words(iw, title_tokens) if title_tokens and iw else None
        start_index = base + (offset if offset is not None else 0)
        db.add(
            DocumentChapter(
                document_id=doc.id, title=title_text, start_word_index=start_index
            )
        )

    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents_with_progress(
    db: AsyncSession,
) -> list[tuple[Document, int, int, datetime | None]]:
    stmt = (
        select(
            Document,
            DocumentContent.word_count,
            DocumentProgress.current_word_index,
            DocumentProgress.last_opened_at,
        )
        .join(DocumentContent, DocumentContent.document_id == Document.id)
        .join(DocumentProgress, DocumentProgress.document_id == Document.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(stmt)
    rows: list[tuple[Document, int, int, datetime | None]] = []
    for row in result.all():
        doc: Document = row[0]
        word_count: int = row[1]
        current_word_index: int = row[2]
        last_opened_at = row[3]
        rows.append((doc, word_count, current_word_index, last_opened_at))
    return rows


async def get_document_with_content(db: AsyncSession, document_id: int) -> tuple[Document, DocumentContent]:
    stmt = (
        select(Document, DocumentContent)
        .join(DocumentContent, DocumentContent.document_id == Document.id)
        .where(Document.id == document_id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return row[0], row[1]


async def get_document_progress(db: AsyncSession, document_id: int) -> DocumentProgress:
    progress = await db.get(DocumentProgress, document_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    return progress


async def update_document_progress(
    db: AsyncSession, document_id: int, *, current_word_index: int
) -> DocumentProgress:
    progress = await get_document_progress(db, document_id)
    progress.current_word_index = max(0, current_word_index)
    progress.last_opened_at = datetime.utcnow()
    await db.commit()
    await db.refresh(progress)
    return progress


async def delete_document(db: AsyncSession, document_id: int) -> None:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    content = await db.get(DocumentContent, document_id)
    if content:
        try:
            Path(content.content_path).unlink(missing_ok=True)
        except OSError:
            pass

    if doc.source_type == "audio_transcript":
        audio_path = settings.data_dir / "audio" / f"{document_id}.mp3"
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass

    await db.delete(doc)
    await db.commit()


async def get_document_structure(
    db: AsyncSession, document_id: int
) -> tuple[list[DocumentChapter], list[DocumentPage]]:
    chapters_stmt = (
        select(DocumentChapter)
        .where(DocumentChapter.document_id == document_id)
        .order_by(DocumentChapter.start_word_index.asc())
    )
    pages_stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
    )
    chapters_result = await db.execute(chapters_stmt)
    pages_result = await db.execute(pages_stmt)
    chapters = [row[0] for row in chapters_result.all()]
    pages = [row[0] for row in pages_result.all()]
    return chapters, pages

