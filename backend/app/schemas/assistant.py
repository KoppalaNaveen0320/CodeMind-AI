from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class AssistantQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[int] = None


class CitationRead(BaseModel):
    source_index: int
    repository_name: str
    file_path: str
    symbol_name: Optional[str] = None
    start_line: int
    end_line: int
    similarity_score: float
    similarity_percent: str
    channels: List[str] = []
    source_revision: str
    snippet: str


class AssistantQueryResponse(BaseModel):
    conversation_id: int
    message_id: int
    answer: str
    repository_id: Optional[int] = None
    repository_name: Optional[str] = None
    citations: List[CitationRead] = []
    related_components: List[Dict[str, Any]] = []
    facts: Dict[str, int] = {}
    risk_callout: Dict[str, Any] = {}
    llm_configured: bool
    retrieval_strategy: str = "hybrid"
    status: str = "success"


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    citations: Optional[List[Dict[str, Any]]] = None
    retrieval_strategy: Optional[str] = None
    evidence_metadata: Optional[Dict[str, Any]] = None
    status: str = "success"
    created_at: datetime


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    title_is_manual: Optional[bool] = None
    repository_id: Optional[int] = None
    branch: Optional[str] = Field(None, max_length=100)


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    title_is_manual: Optional[bool] = None
    is_archived: Optional[bool] = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    repository_id: Optional[int] = None
    repository_name: Optional[str] = None
    repository_full_name: Optional[str] = None
    branch: Optional[str] = None
    title: str
    title_is_manual: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_archived: bool = False
    summary: Optional[str] = None
    messages_count: int = 0
    last_message_preview: Optional[str] = None


class ConversationDetailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    repository_id: Optional[int] = None
    repository_name: Optional[str] = None
    repository_full_name: Optional[str] = None
    branch: Optional[str] = None
    title: str
    title_is_manual: bool = False
    summary: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_archived: bool = False
    messages: List[MessageRead] = []


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    repository_id: Optional[int] = None
    branch: Optional[str] = Field(None, max_length=100)


class FileContentResponse(BaseModel):
    file_path: str
    language: Optional[str] = None
    lines_count: int = 0
    content: str
    highlight_start: Optional[int] = None
    highlight_end: Optional[int] = None
