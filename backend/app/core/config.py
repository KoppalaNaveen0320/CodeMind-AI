from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "CodeMind AI"
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    DEBUG: bool = True

    # Database Configuration
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/codemind_db"
    SQLITE_FALLBACK_URL: str = "sqlite:///./codemind_dev.db"
    ALLOW_SQLITE_FALLBACK: bool = True
    SECRET_KEY: str = "codemind-secure-secret-key-32-chars-long!"

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

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
