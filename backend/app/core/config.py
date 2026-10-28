from typing import Optional
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "CodeMind AI"
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    DEBUG: bool = True

    # Database Configuration
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/codemind_db"
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: Optional[str] = None
    SQLITE_FALLBACK_URL: str = "sqlite:///./codemind_dev.db"
    ALLOW_SQLITE_FALLBACK: bool = True
    SECRET_KEY: str = "codemind-secure-secret-key-32-chars-long!"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE_SECONDS: int = 1800

    # Directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    TEMPLATES_DIR: Path = BASE_DIR / "frontend" / "templates"
    STATIC_DIR: Path = BASE_DIR / "frontend" / "static"
    STORAGE_DIR: Path = BASE_DIR / "backend" / "data"

    # GitHub OAuth / App Configuration
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/github/callback"
    GITHUB_APP_NAME: str = "CodeMind AI"
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_PERSONAL_ACCESS_TOKEN: Optional[str] = None
    GITHUB_TOKEN_ENCRYPTION_KEY: Optional[str] = None

    # GitHub Webhook & Auto-Synchronization Configuration
    GITHUB_WEBHOOK_SECRET: str = "codemind-webhook-secret-change-in-production"
    GITHUB_SYNC_POLLING_INTERVAL_SECONDS: int = 300  # 5 minutes default
    GITHUB_SYNC_POLLING_ENABLED: bool = True
    GITHUB_SYNC_MIN_INTERVAL_SECONDS: int = 60       # Minimum cooldown between sync requests per repo
    GITHUB_SYNC_MAX_CONCURRENT_REQUESTS: int = 3     # Maximum concurrent repository sync checks
    GITHUB_SYNC_BURST_DELAY_SECONDS: float = 1.0     # Delay between polling successive repositories
    GITHUB_RATE_LIMIT_MIN_REMAINING: int = 10        # Minimum remaining quota before pausing background sync
    GITHUB_GIT_FALLBACK_ENABLED: bool = True         # Enable git ls-remote fallback on REST API failure

    # Repository Indexing Limits
    INDEXING_MAX_FILES: int = 2000
    INDEXING_MAX_FILE_SIZE_BYTES: int = 500 * 1024       # 500 KB per file
    INDEXING_MAX_REPO_SIZE_BYTES: int = 100 * 1024 * 1024 # 100 MB total archive
    INDEXING_TIMEOUT_SECONDS: int = 180

    # AI Runtime Configuration (ollama, openai, mock)
    AI_PROVIDER: str = "ollama"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"

    # LLM Configuration
    LLM_PROVIDER: str = "ollama"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen2.5:3b"
    LLM_BASE_URL: str = ""
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT_SECONDS: int = 90
    
    # Embedding Configuration
    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSION: int = 768
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_TIMEOUT_SECONDS: int = 30
    
    # Chunking & Hybrid Retrieval
    CHUNK_SIZE_LINES: int = 60
    CHUNK_OVERLAP_LINES: int = 15
    RETRIEVAL_TOP_K: int = 8
    RETRIEVAL_VECTOR_WEIGHT: float = 0.5
    RETRIEVAL_KEYWORD_WEIGHT: float = 0.3
    RETRIEVAL_EXACT_WEIGHT: float = 0.2
    
    # Knowledge Graph & Impact Analysis
    IMPACT_MAX_DEPTH: int = 3

    # Phase 4 Security, Upload & Rate Limiting Controls
    REQUIRE_AUTH: bool = False
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 15
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 120
    RATE_LIMIT_INDEXING_PER_MINUTE: int = 10
    RATE_LIMIT_ASSISTANT_PER_MINUTE: int = 30
    MAX_UPLOAD_SIZE_BYTES: int = 100 * 1024 * 1024       # 100 MB max archive upload
    MAX_EXTRACTED_SIZE_BYTES: int = 250 * 1024 * 1024     # 250 MB max uncompressed
    MAX_ARCHIVE_FILE_COUNT: int = 5000                   # 5000 files max per archive
    SECURE_COOKIES: Optional[bool] = None
    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"
    TRUSTED_PROXIES: str = "127.0.0.1,::1,localhost"
    SESSION_TIMEOUT_MINUTES: int = 30

    @model_validator(mode="after")
    def assemble_db_url(self) -> "Settings":
        """
        Safely constructs DATABASE_URL with percent-encoded credentials if individual
        POSTGRES_* connection parameters are supplied.
        """
        if self.POSTGRES_USER and self.POSTGRES_PASSWORD and self.POSTGRES_DB and self.POSTGRES_HOST:
            from sqlalchemy.engine import URL
            self.DATABASE_URL = str(
                URL.create(
                    drivername="postgresql+psycopg2",
                    username=self.POSTGRES_USER,
                    password=self.POSTGRES_PASSWORD,
                    host=self.POSTGRES_HOST,
                    port=self.POSTGRES_PORT or 5432,
                    database=self.POSTGRES_DB,
                ).render_as_string(hide_password=False)
            )
        return self

    @property
    def is_cookie_secure(self) -> bool:
        if self.SECURE_COOKIES is not None:
            return self.SECURE_COOKIES
        return self.APP_ENV == "production" and not self.DEBUG

    model_config = SettingsConfigDict(
        env_file=(
            str(Path(__file__).resolve().parent.parent.parent.parent / ".env"),
            str(Path(__file__).resolve().parent.parent.parent / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
