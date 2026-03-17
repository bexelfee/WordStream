from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


SourceType = Literal["text", "pdf", "epub", "audio_transcript"]


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    original_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    filesize_bytes: Mapped[int] = mapped_column(BigInteger)
    language: Mapped[str] = mapped_column(String(16), default="en")
    processing: Mapped[bool] = mapped_column(Boolean, default=False)
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    content: Mapped["DocumentContent"] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    progress: Mapped["DocumentProgress"] = relationship(
        back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    chapters: Mapped[list["DocumentChapter"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentContent(Base):
    __tablename__ = "document_content"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    content_path: Mapped[str] = mapped_column(String(1024))
    word_count: Mapped[int] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="content")


class DocumentProgress(Base):
    __tablename__ = "document_progress"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    current_word_index: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped[Document] = relationship(back_populates="progress")


class DocumentChapter(Base):
    __tablename__ = "document_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    start_word_index: Mapped[int] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="chapters")


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    start_word_index: Mapped[int] = mapped_column(Integer)

    document: Mapped[Document] = relationship(back_populates="pages")

