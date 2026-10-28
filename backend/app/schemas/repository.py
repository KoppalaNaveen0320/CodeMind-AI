from datetime import datetime
from typing import Optional, List, Union
from pydantic import BaseModel, ConfigDict, Field


class TechItemRead(BaseModel):
    name: str
    category: str  # "framework", "language", "database", "orm", "tool", "infrastructure"
    type: Optional[str] = None
    confidence: Union[float, str] = 1.0
    evidence: Optional[List[str]] = Field(default_factory=list)
    evidence_file: Optional[str] = None
    version: Optional[str] = None
    details: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="allow")


class TechStackSummaryRead(BaseModel):
    frontend_text: str = "Not detected"
    backend_text: str = "Not detected"
    database_text: Optional[str] = None
    infrastructure_text: Optional[str] = None
    frontend_summary: Optional[str] = None
    backend_summary: Optional[str] = None
    database_summary: Optional[str] = None
    infrastructure_summary: Optional[str] = None
    full_summary: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="allow")


class TechStackRead(BaseModel):
    frontend: List[TechItemRead] = Field(default_factory=list)
    backend: List[TechItemRead] = Field(default_factory=list)
    database: List[TechItemRead] = Field(default_factory=list)
    infrastructure: List[TechItemRead] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    summary: TechStackSummaryRead = Field(default_factory=TechStackSummaryRead)
    detected_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, extra="allow")

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class RepositoryBase(BaseModel):
    name: str
    full_name: str
    description: Optional[str] = None
    provider: str = "github"
    is_private: bool = True
    default_branch: str = "main"
    primary_language: Optional[str] = None
    github_repo_id: Optional[int] = None
    html_url: Optional[str] = None
    clone_url: Optional[str] = None
    owner_login: Optional[str] = None
    connected_account_id: Optional[int] = None


class RepositoryCreate(RepositoryBase):
    pass


class ConnectPublicRepositoryRequest(BaseModel):
    repository: str
    auto_index: bool = True
    connected_account_id: Optional[int] = None


class RepositoryImportRequest(BaseModel):
    repository_url_or_path: str
    connected_account_id: Optional[int] = None
    default_branch: Optional[str] = None
    auto_index: bool = True


class RepositoryRead(RepositoryBase):
    id: int
    user_id: Optional[int] = None
    connected_account_id: Optional[int] = None
    status: str
    current_revision: Optional[str] = None
    files_count: int
    symbols_count: int
    apis_count: int
    dependencies_count: int
    last_indexed_at: Optional[datetime] = None
    last_synced_commit_sha: Optional[str] = None
    latest_remote_commit_sha: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    sync_status: Optional[str] = "synced"
    sync_error: Optional[str] = None
    sync_error_code: Optional[str] = None
    sync_error_category: Optional[str] = None
    sync_failed_operation: Optional[str] = None
    sync_last_attempt_at: Optional[datetime] = None
    sync_retry_count: int = 0
    sync_suggested_action: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tech_stack: Optional[TechStackRead] = None

    model_config = ConfigDict(from_attributes=True)


class RepositorySyncStatusResponse(BaseModel):
    repository_id: int
    repository_name: str
    full_name: str
    default_branch: str
    branch: Optional[str] = None
    sync_status: str  # synced, update_available, syncing, failed, rate_limited
    last_synced_commit_sha: Optional[str] = None
    last_successful_commit_sha: Optional[str] = None
    latest_remote_commit_sha: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    sync_error: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    error_category: Optional[str] = None
    failed_operation: Optional[str] = None
    suggested_action: Optional[str] = None
    retry_count: int = 0
    reset_at: Optional[datetime] = None
    retry_after: Optional[int] = None
    auth_available: bool = False
    auth_type: str = "unauthenticated"
    rate_limit_remaining: Optional[int] = None
    rate_limit_limit: Optional[int] = None
    next_permitted_sync_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class RepositorySyncDiagnosticsResponse(BaseModel):
    repository_id: int
    full_name: str
    branch: str
    sync_status: str
    auth_available: bool
    auth_type: str
    rate_limit_remaining: Optional[int] = None
    rate_limit_limit: Optional[int] = None
    rate_limit_reset_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    last_successful_sync_at: Optional[datetime] = None
    last_successful_commit_sha: Optional[str] = None
    next_permitted_sync_at: Optional[datetime] = None
    error_category: Optional[str] = None
    error_code: Optional[str] = None
    failed_operation: Optional[str] = None
    retry_count: int = 0
    suggested_action: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
