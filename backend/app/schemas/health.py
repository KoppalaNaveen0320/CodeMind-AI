from typing import Optional
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str = "0.1.0"
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    dialect: Optional[str] = None
    detail: Optional[str] = None
    pgvector_available: bool = False
    ai_provider: Optional[str] = None
    ollama_service_available: bool = False
    llm_model_available: bool = False
    embedding_model_available: bool = False
