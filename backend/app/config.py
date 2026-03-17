from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "WordStream"
    data_dir: Path = Path("/data")
    max_upload_mb: int = 250
    cors_allow_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    transcription_stale_minutes: int = 30
    database_url: str | None = None

    class Config:
        env_prefix = ""
        env_file = ".env"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "app.db"
        return f"sqlite+aiosqlite:///{db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

