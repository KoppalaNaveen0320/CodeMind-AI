from typing import List, Optional
from pydantic import BaseModel
from backend.app.schemas.repository import RepositoryRead


class DashboardOverviewRead(BaseModel):
    greeting: str
    files_indexed: int
    functions_classes: int
    apis_detected: int
    dependencies_mapped: int
    active_repository: Optional[RepositoryRead] = None
    repositories: List[RepositoryRead] = []
    recent_questions: List[dict] = []
