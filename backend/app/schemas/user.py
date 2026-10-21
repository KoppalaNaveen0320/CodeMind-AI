from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    email: str
    full_name: str
    workspace_name: str = "Acme Engineering"
    avatar_initials: str = "AK"


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
