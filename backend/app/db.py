from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.resolved_database_url, future=True, echo=False)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


def _add_processing_column_if_missing(sync_conn):
    """Add Document.processing column for existing databases."""
    from sqlalchemy import text
    try:
        sync_conn.execute(text("ALTER TABLE documents ADD COLUMN processing INTEGER DEFAULT 0"))
    except Exception:
        # Column already exists or other DB-specific error
        pass


def _add_transcription_error_column_if_missing(sync_conn):
    """Add Document.transcription_error column for existing databases."""
    from sqlalchemy import text
    try:
        sync_conn.execute(text("ALTER TABLE documents ADD COLUMN transcription_error TEXT"))
    except Exception:
        # Column already exists or other DB-specific error
        pass


async def init_db() -> None:
    """Create database tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_processing_column_if_missing)
        await conn.run_sync(_add_transcription_error_column_if_missing)

