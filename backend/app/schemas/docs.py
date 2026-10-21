from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class DocModule(BaseModel):
    name: str
    file_path: str
    language: Optional[str] = None
    lines_count: int = 0
    symbols_count: int = 0
    symbols: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


class RepositoryDocsResponse(BaseModel):
    repository_id: int
    repository_name: str
    overview: str
    total_files: int
    total_symbols: int
    modules: List[DocModule] = []

    model_config = ConfigDict(from_attributes=True)
