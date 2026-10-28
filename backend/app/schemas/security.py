from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class SecurityFindingItem(BaseModel):
    id: str
    rule_id: str
    cwe: str
    title: str
    severity: str  # HIGH, MEDIUM, LOW
    file_path: str
    line_number: int
    snippet: str
    why_it_matters: str
    remediation: str
    status: str = "OPEN"  # OPEN, ACKNOWLEDGED, REVIEWED, DISMISSED
    confidence: str = "HIGH"
    category: Optional[str] = "Security"
    remediation_steps: Optional[List[str]] = []

    model_config = ConfigDict(from_attributes=True)


class SecurityScanSummary(BaseModel):
    repository_id: int
    repository_name: Optional[str] = None
    branch: Optional[str] = None
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    reviewed_count: int = 0
    total_findings: int = 0
    findings: List[SecurityFindingItem] = []
    scanned_at: Optional[str] = None
    status: str = "completed"  # completed, indexing_in_progress, failed
    message: Optional[str] = None
    files_scanned: int = 0
    total_files: int = 0

    model_config = ConfigDict(from_attributes=True)


class FindingStatusUpdateRequest(BaseModel):
    status: str  # OPEN, ACKNOWLEDGED, REVIEWED, DISMISSED
