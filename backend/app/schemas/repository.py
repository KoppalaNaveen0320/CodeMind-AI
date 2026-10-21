from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


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


class RepositoryCreate(RepositoryBase):
    pass


class ConnectPublicRepositoryRequest(BaseModel):
    repository: str
    auto_index: bool = True


class RepositoryRead(RepositoryBase):
    id: int
    user_id: Optional[int] = None
    status: str
    current_revision: Optional[str] = None
    files_count: int
    symbols_count: int
    apis_count: int
    dependencies_count: int
    last_indexed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
