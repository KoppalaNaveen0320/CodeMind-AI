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

    model_config = ConfigDict(from_attributes=True)


class SecurityScanSummary(BaseModel):
    repository_id: int
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    reviewed_count: int = 0
    total_findings: int = 0
    findings: List[SecurityFindingItem] = []

    model_config = ConfigDict(from_attributes=True)


class FindingStatusUpdateRequest(BaseModel):
    status: str  # OPEN, ACKNOWLEDGED, REVIEWED, DISMISSED
