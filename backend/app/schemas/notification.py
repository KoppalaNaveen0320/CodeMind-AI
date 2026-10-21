from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class NotificationItem(BaseModel):
    id: str
    type: str  # indexing, security, system
    title: str
    message: str
    timestamp: str
    time_ago: str
    status: str  # info, success, warning, danger
    link: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    unread_count: int = 0
    notifications: List[NotificationItem] = []

    model_config = ConfigDict(from_attributes=True)
