import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "RAG-PDF-System"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "data" / "raw"
    PROCESSED_DIR: Path = BASE_DIR / "data" / "processed"
    VECTOR_DIR: Path = BASE_DIR / "data" / "vectors"

    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    DASHSCOPE_API_KEY: Optional[str] = None
    EMBEDDING_MODEL: str = "text-embedding-v1"
    EMBEDDING_BATCH_SIZE: int = 20
    EMBEDDING_MAX_BATCH_SIZE: int = 25
    LLM_MODEL: str = "qwen3.7-max"

    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION_NAME: str = "rag_documents_v2"
    MILVUS_DIMENSION: int = 1536

    REDIS_URL: str = "redis://localhost:6379/0"
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = ""
    RABBITMQ_PASSWORD: str = ""
    
    # MinIO Config
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_NAME: str = "rag-documents"
    MINIO_SECURE: bool = False

    # SQL Database
    DATABASE_URL: str = "postgresql+psycopg://rag_user:rag_password@localhost:5432/rag_system"
    
    # RAG Config
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K: int = 20
    
    # Rerank Config
    ENABLE_RERANK: bool = True
    RERANK_MODEL: str = "gte-rerank"  # DashScope rerank model
    RERANK_TOP_N: int = 5
    
    # Multi-hop Config
    ENABLE_MULTI_HOP: bool = True
    MAX_HOP: int = 3

    # Memory Config
    SHORT_TERM_MEMORY_TTL: int = 3600  # 1 hour
    LONG_TERM_MEMORY_COLLECTION: str = "user_memory"
    MEMORY_HISTORY_LIMIT: int = 10

    # Durable Agent execution
    AGENT_MAX_TIMEOUT_SECONDS: int = 300
    AGENT_RUN_CACHE_TTL: int = 86400
    AGENT_SSE_POLL_INTERVAL: float = 0.25

    # Note / AI Config
    NOTE_AUTO_SAVE_DELAY: int = 3000
    AI_COMPLETION_MAX_TOKENS: int = 100
    AI_WRITING_MAX_TOKENS: int = 512
    AI_COMPLETION_TRIGGER_CHARS: int = 3
    AI_COMPLETION_DEBOUNCE_MS: int = 1500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.PROCESSED_DIR, exist_ok=True)
os.makedirs(settings.VECTOR_DIR, exist_ok=True)
