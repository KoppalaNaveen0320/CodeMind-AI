from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class SecurityFindingStatus(Base):
    __tablename__ = "security_finding_statuses"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    finding_id = Column(String(100), nullable=False, index=True)
    status = Column(String(50), default="OPEN", nullable=False)  # OPEN, ACKNOWLEDGED, REVIEWED, DISMISSED
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    repository = relationship("Repository", backref="security_finding_statuses")

    __table_args__ = (
        UniqueConstraint("repository_id", "finding_id", name="uq_repo_finding_status"),
    )
