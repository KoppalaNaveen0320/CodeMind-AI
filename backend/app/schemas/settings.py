from typing import Optional
from pydantic import BaseModel, ConfigDict
from backend.app.schemas.user import UserRead


class UserSettingsResponse(BaseModel):
    user: UserRead
    app_name: str
    app_env: str
    ai_provider: str
    llm_model: str
    embedding_model: str
    embedding_dimension: int
    github_configured: bool
    github_connected: bool
    github_username: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    workspace_name: Optional[str] = None
