from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GraphNodeRead(BaseModel):
    id: int
    key: str
    type: str
    name: str
    file_path: Optional[str] = None
    symbol_name: Optional[str] = None
    signature: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    language: Optional[str] = None
    properties: Dict[str, Any] = {}


class GraphEdgeRead(BaseModel):
    id: int
    source: int
    target: int
    source_node_id: Optional[int] = None
    target_node_id: Optional[int] = None
    type: str
    edge_type: Optional[str] = None
    is_verified: bool = True
    evidence: Optional[str] = None
    source_name: Optional[str] = None
    target_name: Optional[str] = None


class GraphSummaryRead(BaseModel):
    total_nodes: int
    total_edges: int
    displayed_nodes: int
    displayed_edges: int
    node_types: Dict[str, int] = {}
    edge_types: Dict[str, int] = {}


class RepositoryGraphResponse(BaseModel):
    repository_id: int
    nodes: List[GraphNodeRead]
    edges: List[GraphEdgeRead]
    summary: GraphSummaryRead


class NodeNeighborsResponse(BaseModel):
    node: Optional[Dict[str, Any]] = None
    incoming: List[Dict[str, Any]] = []
    outgoing: List[Dict[str, Any]] = []
    direct_incoming: List[Dict[str, Any]] = []
    direct_outgoing: List[Dict[str, Any]] = []
    transitive_incoming: List[Dict[str, Any]] = []
    transitive_outgoing: List[Dict[str, Any]] = []
    direct_neighbors: List[Dict[str, Any]] = Field(default_factory=list)
    transitive_neighbors: List[Dict[str, Any]] = Field(default_factory=list)
    depth: int = 1
    has_cycles: bool = False


class GraphPathResponse(BaseModel):
    path: Optional[List[Dict[str, Any]]] = None


class CallHierarchyItem(BaseModel):
    node_id: Optional[int] = None
    symbol_id: Optional[int] = None
    symbol_name: str
    caller_name: Optional[str] = None
    callee_name: Optional[str] = None
    kind: str = "function"
    file_path: str
    caller_file_path: Optional[str] = None
    callee_file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    caller_start_line: Optional[int] = None
    callee_start_line: Optional[int] = None
    caller_end_line: Optional[int] = None
    callee_end_line: Optional[int] = None
    call_line: Optional[int] = None
    call_site_line: Optional[int] = None
    evidence: Optional[str] = None
    is_verified: bool = True
    is_ambiguous: bool = False
    depth: int = 1
    calls: List[Dict[str, Any]] = []


class CallHierarchyResponse(BaseModel):
    repository_id: int
    repository_name: Optional[str] = None
    target_symbol: Dict[str, Any]
    direction: str = "both"  # callers, callees, both
    max_depth: int = 2
    has_cycles: bool = False
    callers: List[CallHierarchyItem] = []
    callees: List[CallHierarchyItem] = []
    total_callers: int = 0
    total_callees: int = 0
    is_ambiguous: bool = False
    candidates: List[Dict[str, Any]] = []
    ambiguous_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    explanation: Optional[str] = None
