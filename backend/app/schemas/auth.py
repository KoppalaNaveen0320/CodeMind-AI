from typing import Optional
from pydantic import BaseModel, Field
from backend.app.schemas.user import UserRead


class UserRegisterRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")
    full_name: str = Field(..., min_length=2)
    workspace_name: Optional[str] = "My Workspace"


class UserLoginRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="Valid email address")
    password: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    success: bool
    message: str
    user: Optional[UserRead] = None
    token: Optional[str] = None


class LogoutResponse(BaseModel):
    success: bool
    message: str
