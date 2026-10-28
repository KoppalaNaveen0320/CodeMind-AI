from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class SessionRead(BaseModel):
    id: int
    user_id: int
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    device_label: str
    browser: Optional[str] = None
    os: Optional[str] = None
    ip_address: Optional[str] = None
    login_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    logout_at: Optional[datetime] = None
    last_accessed_path: str
    status: str
    is_current: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    sessions: List[SessionRead]
    total_count: int
    current_session_id: Optional[int] = None


class SessionRevokeResponse(BaseModel):
    success: bool
    message: str
    is_current: bool = False


class RevokeOthersResponse(BaseModel):
    success: bool
    revoked_count: int
    message: str


class SessionTimeoutUpdateRequest(BaseModel):
    timeout_minutes: int  # 30, 60, 240, 480


class SessionTimeoutUpdateResponse(BaseModel):
    success: bool
    timeout_minutes: int
    message: str
