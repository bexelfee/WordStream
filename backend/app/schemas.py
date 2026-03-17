from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


SourceType = Literal["text", "pdf", "epub", "audio_transcript"]


class DocumentBase(BaseModel):
    title: str
    author: Optional[str] = None
    source_type: SourceType
    original_file_name: Optional[str] = None
    filesize_bytes: int
    language: str = "en"


class DocumentCreateText(BaseModel):
    title: str
    author: Optional[str] = None
    text: str


class DocumentUpdateText(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None


class DocumentSummary(BaseModel):
    id: int
    title: str
    author: Optional[str]
    source_type: SourceType
    original_file_name: Optional[str]
    filesize_bytes: int
    word_count: int
    words_read: int
    created_at: datetime
    updated_at: datetime
    percent_complete: float
    last_opened_at: Optional[datetime]
    processing: bool = False
    transcription_error: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentDetail(BaseModel):
    id: int
    title: str
    author: Optional[str]
    source_type: SourceType
    original_file_name: Optional[str]
    filesize_bytes: int
    language: str
    created_at: datetime
    updated_at: datetime
    word_count: int
    has_chapters: bool
    has_pages: bool
    processing: bool = False
    transcription_error: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentStructureChapter(BaseModel):
    id: int
    title: str
    start_word_index: int


class DocumentStructurePage(BaseModel):
    id: int
    page_number: int
    start_word_index: int


class DocumentStructure(BaseModel):
    chapters: list[DocumentStructureChapter]
    pages: list[DocumentStructurePage]


class DocumentProgress(BaseModel):
    current_word_index: int
    word_count: int
    last_opened_at: Optional[datetime]


class DocumentProgressUpdate(BaseModel):
    current_word_index: int


class DocumentContentResponse(BaseModel):
    text: str
    processing: Optional[bool] = None
    processing_error: Optional[str] = None

