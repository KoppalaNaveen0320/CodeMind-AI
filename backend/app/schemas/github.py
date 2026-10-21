from typing import Optional, List
from pydantic import BaseModel


class GitHubAuthStatusResponse(BaseModel):
    configured: bool
    connected: bool
    username: Optional[str] = None
    avatar_url: Optional[str] = None


class GitHubLoginResponse(BaseModel):
    authorization_url: str
    state: str


class GitHubRepositoryItem(BaseModel):
    id: int
    name: str
    full_name: str
    description: Optional[str] = None
    is_private: bool = True
    default_branch: str = "main"
    html_url: Optional[str] = None
    primary_language: Optional[str] = None
    is_connected: bool = False
