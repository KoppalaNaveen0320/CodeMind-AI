from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SymbolSearchItem(BaseModel):
    id: int
    name: str
    kind: str  # function, method, class, variable, constant, interface, type, import
    symbol_type: Optional[str] = None
    repository_id: int
    repository_name: str
    repository_full_name: Optional[str] = None
    file_path: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0
    signature: Optional[str] = None
    docstring: Optional[str] = None
    preview: Optional[str] = None
    snippet: Optional[str] = None
    language: Optional[str] = None
    match_type: str = "partial"  # "exact", "prefix", "partial"
    score: float = 0.0


class SymbolSearchResponse(BaseModel):
    query: str
    total_count: int
    page: int
    per_page: int
    results: List[SymbolSearchItem]
    symbols: List[SymbolSearchItem] = Field(default_factory=list)
    has_more: bool = False
    filters_applied: Dict[str, Any] = {}


class SymbolDetailResponse(BaseModel):
    id: int
    name: str
    kind: str
    symbol_type: Optional[str] = None
    repository_id: int
    repository_name: str
    repository_full_name: Optional[str] = None
    file_path: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0
    signature: Optional[str] = None
    docstring: Optional[str] = None
    preview: Optional[str] = None
    snippet: Optional[str] = None
    language: Optional[str] = None
    has_callers: bool = False
    has_callees: bool = False
    incoming_calls_count: int = 0
    outgoing_calls_count: int = 0
