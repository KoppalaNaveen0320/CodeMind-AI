from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class IndexedFile(Base):
    __tablename__ = "indexed_files"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(500), nullable=False, index=True)
    language = Column(String(50), nullable=True)
    size_bytes = Column(Integer, default=0, nullable=False)
    content_hash = Column(String(64), nullable=True) # SHA-256
    lines_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repository = relationship("Repository", back_populates="indexed_files")
    symbols = relationship("CodeSymbol", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_indexed_files_repo_path", "repository_id", "path"),
    )
