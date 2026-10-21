from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="QUEUED", nullable=False) # QUEUED, CLONING, PARSING, INDEXING, COMPLETED, FAILED, CANCELLED
    stage = Column(String(50), default="QUEUED", nullable=False)
    branch = Column(String(100), default="main", nullable=False)
    commit_sha = Column(String(100), nullable=True)
    progress_percent = Column(Integer, default=0, nullable=False)
    files_processed = Column(Integer, default=0, nullable=False)
    total_files = Column(Integer, default=0, nullable=False)
    files_added = Column(Integer, default=0, nullable=False)
    files_modified = Column(Integer, default=0, nullable=False)
    files_unchanged = Column(Integer, default=0, nullable=False)
    files_deleted = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    repository = relationship("Repository", back_populates="indexing_jobs")
