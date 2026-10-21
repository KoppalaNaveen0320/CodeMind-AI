from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ImpactAnalyzeRequest(BaseModel):
    component_name: Optional[str] = None
    file_path: Optional[str] = None
    proposed_change: Optional[str] = Field(default="", max_length=2000)
    max_depth: Optional[int] = Field(default=3, ge=1, le=5)


class AffectedComponentRead(BaseModel):
    node_id: int
    name: str
    component_type: str
    file_path: Optional[str] = None
    impact_level: str  # DIRECT, TRANSITIVE
    distance: int
    confidence_score: float = Field(
        ...,
        description="Heuristic confidence score based on topological distance (1.0 for direct 1-hop, decaying by 0.25 per transitive hop); not a calibrated statistical probability."
    )
    evidence: Optional[str] = None
    dependency_path: List[str] = []


class ImpactAnalyzeResponse(BaseModel):
    target_component: str
    target_type: str
    file_path: Optional[str] = None
    proposed_change: Optional[str] = None
    total_affected: int
    direct_count: int
    transitive_count: int
    risk_level: str  # LOW, MEDIUM, HIGH
    affected_components: List[AffectedComponentRead]
    affected_files: List[str]
    dependency_paths: List[Dict[str, Any]]
    limitations: str
    explanation: str
    direct_symbols_count: int = 0
    transitive_symbols_count: int = 0
    direct_files_count: int = 0
    transitive_files_count: int = 0
    external_dependencies: List[str] = []

