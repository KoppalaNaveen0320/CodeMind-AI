from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SearchQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: Optional[int] = Field(default=8, ge=1, le=50)
    language: Optional[str] = None
    expand_graph: bool = True


class SearchChunkResponse(BaseModel):
    chunk_id: int
    repository_id: int
    file_path: str
    symbol_name: Optional[str] = None
    start_line: int
    end_line: int
    chunk_text: str
    score: float
    channels: List[str] = []
    source_revision: Optional[str] = None
    language: Optional[str] = None


class SearchResultResponse(BaseModel):
    query: str
    results_count: int
    results: List[SearchChunkResponse]


class EmbeddingStatusResponse(BaseModel):
    provider: str
    model: str
    dimension: int
    configured: bool
    message: str
    total_chunks: int = 0
    embedded_chunks: int = 0
    unembedded_chunks: int = 0
    base_url: Optional[str] = None
    service_available: bool = False
    model_available: bool = False
    verified_dimension: Optional[int] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_service_available: bool = False
    llm_model_available: bool = False
    database_connected: bool = False
    pgvector_available: bool = False
