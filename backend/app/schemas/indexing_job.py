from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class IndexTriggerRequest(BaseModel):
    branch: Optional[str] = None
    force_full_rebuild: bool = False


class IndexingJobBase(BaseModel):
    repository_id: int
    status: str = "QUEUED"
    stage: str = "QUEUED"
    branch: str = "main"
    commit_sha: Optional[str] = None
    progress_percent: int = 0
    files_processed: int = 0
    total_files: int = 0
    files_added: int = 0
    files_modified: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    error_message: Optional[str] = None


class IndexingJobCreate(IndexingJobBase):
    pass


class IndexingJobRead(IndexingJobBase):
    id: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class IndexingStatusResponse(BaseModel):
    repository_id: int
    status: str
    current_job: Optional[IndexingJobRead] = None
    last_indexed_at: Optional[datetime] = None
    files_count: int
    symbols_count: int
    current_revision: Optional[str] = None
