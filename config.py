import os
from pathlib import Path
from typing import List, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for PerfusionGPT backend.
    All settings can be overridden via environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application Info
    APP_NAME: str = "PerfusionGPT"
    APP_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v: Any) -> bool:
        """Safely parse boolean even if system environment has DEBUG='release' or similar."""
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on", "debug", "dev")
        return False

    # Groq API Configuration
    GROQ_API_KEY: str = Field(default="", description="API Key for Groq cloud API")
    GROQ_MODEL: str = Field(
        default="qwen/qwen3.8-27b",
        description="Supported Groq chat model (e.g., qwen/qwen3.8-27b, openai/gpt-oss-120b, openai/gpt-oss-20b)"
    )
    GROQ_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=2.0)
    GROQ_MAX_TOKENS: int = Field(default=3500, ge=1, le=8192)
    GROQ_REQUEST_TIMEOUT: float = Field(default=45.0, ge=1.0)

    # Google OAuth 2.0 Authentication
    GOOGLE_CLIENT_ID: str = Field(default="", description="Google Cloud OAuth 2.0 Web Client ID")
    GOOGLE_CLIENT_SECRET: str = Field(default="", description="Google Cloud OAuth 2.0 Web Client Secret")

    # Supabase Authentication Configuration
    SUPABASE_URL: str = Field(default="", description="Supabase project URL (e.g. https://xyzcompany.supabase.co)")
    SUPABASE_ANON_KEY: str = Field(default="", description="Supabase publishable/anon API key")
    SUPABASE_SERVICE_ROLE_KEY: str = Field(default="", description="Supabase service role secret API key (optional)")

    # Embedding Configuration (BAAI/bge-small-en-v1.5)
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DIMENSION: int = 384

    # Document Ingestion & Chunking
    MAX_UPLOAD_SIZE_MB: int = 50
    CHUNK_SIZE: int = Field(default=500, description="Target chunk size in approximate tokens/words")
    CHUNK_OVERLAP: int = Field(default=80, description="Overlap between consecutive chunks in tokens/words")
    LOW_TEXT_PAGE_THRESHOLD: int = 40  # Characters below which a page is considered low-text
    OCR_PAGE_RATIO_WARNING: float = 0.5  # If >50% pages have low text, trigger OCR warning

    # Retrieval Configuration
    TOP_K_SEMANTIC: int = 15
    TOP_K_BM25: int = 15
    TOP_K_FINAL: int = 5
    RRF_K: int = 60  # Reciprocal Rank Fusion constant
    MIN_RRF_SCORE_THRESHOLD: float = 0.005  # Threshold below which evidence is flagged insufficient

    # Reranking Configuration
    RERANKING_ENABLED: bool = False
    RERANKER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # CORS Configuration
    CORS_ORIGINS: List[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # PostgreSQL Database Configuration
    DATABASE_URL: str = Field(
        default="",
        description="PostgreSQL connection string (e.g. postgresql://user:pass@ep-xyz.aws.neon.tech/neondb?sslmode=require)"
    )
    DATABASE_ECHO: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: Any) -> str:
        """Normalize legacy postgres:// prefix to standard postgresql:// for SQLAlchemy."""
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("postgres://"):
                v = "postgresql://" + v[len("postgres://"):]
        return v or ""
    BASE_DATA_DIR: Path = Path("data")
    DOCUMENTS_DIR: Path = Path("data/documents")
    INDICES_DIR: Path = Path("data/indices")
    METADATA_FILE: Path = Path("data/metadata.json")

    def ensure_directories(self) -> None:
        """Create necessary data storage directories if they do not exist."""
        self.BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        self.INDICES_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()

