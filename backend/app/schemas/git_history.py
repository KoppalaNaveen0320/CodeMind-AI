from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class CommitListItem(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: Optional[str] = None
    author_date: Optional[str] = None
    time_ago: str = "Recently"
    additions: int = 0
    deletions: int = 0
    files_count: int = 0
    verified: bool = True

    model_config = ConfigDict(from_attributes=True)


class CommitFileChange(BaseModel):
    filename: str
    status: str = "modified"  # modified, added, removed, renamed
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None
    is_binary: bool = False
    previous_filename: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CommitDetailResponse(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: Optional[str] = None
    author_date: Optional[str] = None
    time_ago: str = "Recently"
    parent_shas: List[str] = []
    branch: str = "main"
    total_files: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    files: List[CommitFileChange] = []
    ai_explanation: Optional[str] = None
    confirmed_explanation: Optional[str] = None
    inferred_explanation: Optional[str] = None
    citations: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


class CommitListResponse(BaseModel):
    repository_id: int
    branch: str
    total_commits: int
    commits: List[CommitListItem]
    has_more: bool = False

    model_config = ConfigDict(from_attributes=True)
