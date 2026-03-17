import asyncio
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db, init_db
from . import schemas
from .services import (
    create_text_document,
    create_pdf_document,
    create_epub_document,
    create_audio_document,
    run_transcription_for_document,
    delete_document,
    get_document_progress,
    get_document_with_content,
    get_document_structure,
    list_documents_with_progress,
    update_document_progress,
    update_text_document,
    recover_incomplete_transcriptions,
)


settings = get_settings()
app = FastAPI(title=settings.app_name)
allowed_origins = [
    origin.strip()
    for origin in settings.cors_allow_origins.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()
    retry_ids = await recover_incomplete_transcriptions()
    for doc_id in retry_ids:
        asyncio.create_task(run_transcription_for_document(doc_id))


@app.get("/health", tags=["system"])
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    # Simple dependency check to ensure DB session can be created
    return {"status": "ok"}


@app.get("/api/config", tags=["system"])
async def get_config() -> dict:
    """Public config for the frontend (e.g. HF token set for model downloads)."""
    return {
        "hf_token_configured": bool(os.environ.get("HF_TOKEN")),
    }


@app.post("/api/documents/upload", response_model=schemas.DocumentDetail, tags=["documents"])
async def upload_document_endpoint(
    file: UploadFile = File(...),
    title: str | None = None,
    author: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    max_bytes = settings.max_upload_mb * 1024 * 1024
    read_bytes = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        read_bytes += len(chunk)
        if read_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    data = b"".join(chunks)

    filename = file.filename or "document"
    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        doc = await create_pdf_document(
            db,
            file_bytes=data,
            original_file_name=filename,
            title=title,
            author=author,
        )
    elif lower_name.endswith(".epub"):
        doc = await create_epub_document(
            db,
            file_bytes=data,
            original_file_name=filename,
            title=title,
            author=author,
        )
    elif lower_name.endswith(".mp3"):
        doc = await create_audio_document(
            db,
            file_bytes=data,
            original_file_name=filename,
            title=title,
            author=author,
        )
        asyncio.create_task(run_transcription_for_document(doc.id))
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Load content for detail response
    doc_loaded, content = await get_document_with_content(db, doc.id)
    chapters, pages = await get_document_structure(db, doc.id)
    has_chapters = bool(chapters)
    has_pages = bool(pages)
    return schemas.DocumentDetail(
        id=doc_loaded.id,
        title=doc_loaded.title,
        author=doc_loaded.author,
        source_type=doc_loaded.source_type,  # type: ignore[arg-type]
        original_file_name=doc_loaded.original_file_name,
        filesize_bytes=doc_loaded.filesize_bytes,
        language=doc_loaded.language,
        created_at=doc_loaded.created_at,
        updated_at=doc_loaded.updated_at,
        word_count=content.word_count,
        has_chapters=has_chapters,
        has_pages=has_pages,
        processing=getattr(doc_loaded, "processing", False),
        transcription_error=getattr(doc_loaded, "transcription_error", None),
    )


@app.post("/api/documents/text", response_model=schemas.DocumentDetail, tags=["documents"])
async def create_text_endpoint(
    payload: schemas.DocumentCreateText, db: AsyncSession = Depends(get_db)
):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty")
    doc = await create_text_document(
        db, title=payload.title, author=payload.author, text=payload.text
    )
    # Load related content to populate detail fields
    doc_loaded, content = await get_document_with_content(db, doc.id)
    return schemas.DocumentDetail(
        id=doc_loaded.id,
        title=doc_loaded.title,
        author=doc_loaded.author,
        source_type=doc_loaded.source_type,  # type: ignore[arg-type]
        original_file_name=doc_loaded.original_file_name,
        filesize_bytes=doc_loaded.filesize_bytes,
        language=doc_loaded.language,
        created_at=doc_loaded.created_at,
        updated_at=doc_loaded.updated_at,
        word_count=content.word_count,
        has_chapters=False,
        has_pages=False,
        processing=getattr(doc_loaded, "processing", False),
        transcription_error=getattr(doc_loaded, "transcription_error", None),
    )


@app.post(
    "/api/documents/{document_id}/text",
    response_model=schemas.DocumentDetail,
    tags=["documents"],
)
async def update_text_endpoint(
    document_id: int,
    payload: schemas.DocumentUpdateText,
    db: AsyncSession = Depends(get_db),
):
    doc = await update_text_document(
        db, document_id=document_id, title=payload.title, text=payload.text
    )
    doc_loaded, content = await get_document_with_content(db, doc.id)
    return schemas.DocumentDetail(
        id=doc_loaded.id,
        title=doc_loaded.title,
        author=doc_loaded.author,
        source_type=doc_loaded.source_type,  # type: ignore[arg-type]
        original_file_name=doc_loaded.original_file_name,
        filesize_bytes=doc_loaded.filesize_bytes,
        language=doc_loaded.language,
        created_at=doc_loaded.created_at,
        updated_at=doc_loaded.updated_at,
        word_count=content.word_count,
        has_chapters=False,
        has_pages=False,
        processing=getattr(doc_loaded, "processing", False),
        transcription_error=getattr(doc_loaded, "transcription_error", None),
    )


@app.get("/api/documents", response_model=list[schemas.DocumentSummary], tags=["documents"])
async def list_documents_endpoint(db: AsyncSession = Depends(get_db)):
    rows = await list_documents_with_progress(db)
    summaries: list[schemas.DocumentSummary] = []
    for doc, word_count, current_word_index, last_opened_at in rows:
        if word_count > 0:
            words_read = min(word_count, current_word_index + 1)
            percent_complete = float(words_read) / word_count * 100.0
        else:
            words_read = 0
            percent_complete = 0.0
        summaries.append(
            schemas.DocumentSummary(
                id=doc.id,
                title=doc.title,
                author=doc.author,
                source_type=doc.source_type,  # type: ignore[arg-type]
                original_file_name=doc.original_file_name,
                filesize_bytes=doc.filesize_bytes,
                word_count=word_count,
                words_read=words_read,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                percent_complete=percent_complete,
                last_opened_at=last_opened_at,
                processing=getattr(doc, "processing", False),
                transcription_error=getattr(doc, "transcription_error", None),
            )
        )
    return summaries


@app.get(
    "/api/documents/{document_id}",
    response_model=schemas.DocumentDetail,
    tags=["documents"],
)
async def get_document_endpoint(
    document_id: int, db: AsyncSession = Depends(get_db)
):
    doc_loaded, content = await get_document_with_content(db, document_id)
    chapters, pages = await get_document_structure(db, document_id)
    return schemas.DocumentDetail(
        id=doc_loaded.id,
        title=doc_loaded.title,
        author=doc_loaded.author,
        source_type=doc_loaded.source_type,  # type: ignore[arg-type]
        original_file_name=doc_loaded.original_file_name,
        filesize_bytes=doc_loaded.filesize_bytes,
        language=doc_loaded.language,
        created_at=doc_loaded.created_at,
        updated_at=doc_loaded.updated_at,
        word_count=content.word_count,
        has_chapters=bool(chapters),
        has_pages=bool(pages),
        processing=getattr(doc_loaded, "processing", False),
        transcription_error=getattr(doc_loaded, "transcription_error", None),
    )


@app.get(
    "/api/documents/{document_id}/content",
    response_model=schemas.DocumentContentResponse,
    tags=["documents"],
)
async def get_document_content_endpoint(
    document_id: int, db: AsyncSession = Depends(get_db)
):
    doc, content = await get_document_with_content(db, document_id)
    if getattr(doc, "processing", False):
        return schemas.DocumentContentResponse(
            text="",
            processing=True,
            processing_error=getattr(doc, "transcription_error", None),
        )
    text_path = content.content_path
    try:
        data = Path(text_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Content file missing")
    return schemas.DocumentContentResponse(
        text=data,
        processing=False,
        processing_error=getattr(doc, "transcription_error", None),
    )


@app.get(
    "/api/documents/{document_id}/progress",
    response_model=schemas.DocumentProgress,
    tags=["documents"],
)
async def get_progress_endpoint(
    document_id: int, db: AsyncSession = Depends(get_db)
):
    progress = await get_document_progress(db, document_id)
    _, content = await get_document_with_content(db, document_id)
    return schemas.DocumentProgress(
        current_word_index=progress.current_word_index,
        word_count=content.word_count,
        last_opened_at=progress.last_opened_at,
    )


@app.put(
    "/api/documents/{document_id}/progress",
    response_model=schemas.DocumentProgress,
    tags=["documents"],
)
async def update_progress_endpoint(
    document_id: int,
    body: schemas.DocumentProgressUpdate,
    db: AsyncSession = Depends(get_db),
):
    progress = await update_document_progress(
        db, document_id=document_id, current_word_index=body.current_word_index
    )
    _, content = await get_document_with_content(db, document_id)
    return schemas.DocumentProgress(
        current_word_index=progress.current_word_index,
        word_count=content.word_count,
        last_opened_at=progress.last_opened_at,
    )


@app.delete("/api/documents/{document_id}", status_code=204, tags=["documents"])
async def delete_document_endpoint(
    document_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    await delete_document(db, document_id=document_id)


@app.get(
    "/api/documents/{document_id}/structure",
    response_model=schemas.DocumentStructure,
    tags=["documents"],
)
async def get_document_structure_endpoint(
    document_id: int, db: AsyncSession = Depends(get_db)
):
    chapters, pages = await get_document_structure(db, document_id)
    return schemas.DocumentStructure(
        chapters=[
            schemas.DocumentStructureChapter(
                id=c.id, title=c.title, start_word_index=c.start_word_index
            )
            for c in chapters
        ],
        pages=[
            schemas.DocumentStructurePage(
                id=p.id, page_number=p.page_number, start_word_index=p.start_word_index
            )
            for p in pages
        ],
    )


# Serve built frontend (SPA): static assets and index.html fallback
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api" or full_path == "health":
            raise HTTPException(status_code=404, detail="Not found")
        path = (_FRONTEND_DIST / full_path).resolve()
        try:
            path.relative_to(_FRONTEND_DIST)
        except ValueError:
            return FileResponse(_FRONTEND_DIST / "index.html")
        if path.is_file():
            return FileResponse(path)
        return FileResponse(_FRONTEND_DIST / "index.html")
