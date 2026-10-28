from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, model_validator


class GitHubPersonalAccessTokenRequest(BaseModel):
    personal_access_token: Optional[str] = Field(None, description="Masked Personal Access Token (classic or fine-grained)")
    token: Optional[str] = Field(None, description="Alias for personal_access_token")
    label: Optional[str] = Field(None, description="Optional descriptive label for this account/token")

    @model_validator(mode="before")
    @classmethod
    def populate_token_fields(cls, values):
        if isinstance(values, dict):
            val = values.get("personal_access_token") or values.get("token")
            if not val:
                raise ValueError("personal_access_token is required")
            values["personal_access_token"] = val
            values["token"] = val
        return values


class GitHubConnectedAccountResponse(BaseModel):
    id: int
    user_id: int
    github_user_id: Optional[str] = None
    github_username: str
    account_type: str = "user"
    auth_method: str = "oauth"
    label: Optional[str] = None
    avatar_url: Optional[str] = None
    token_scope: Optional[str] = None
    token_type: Optional[str] = "bearer"
    token_expires_at: Optional[datetime] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GitHubAccountListResponse(BaseModel):
    accounts: List[GitHubConnectedAccountResponse]
    total_count: int


class GitHubAuthStatusResponse(BaseModel):
    configured: bool
    connected: bool
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    connected_accounts_count: int = 0
    accounts: List[GitHubConnectedAccountResponse] = Field(default_factory=list)


class GitHubLoginResponse(BaseModel):
    authorization_url: str
    state: str


class GitHubDisconnectResponse(BaseModel):
    status: str
    message: str
    revoked_remotely: bool = False


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
    connected_account_id: Optional[int] = None
