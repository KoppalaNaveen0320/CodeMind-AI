from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship, deferred
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from backend.app.db.session import Base
from backend.app.core.config import settings


class CodeChunk(Base):
    __tablename__ = "code_chunks"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("indexed_files.id", ondelete="CASCADE"), nullable=True, index=True)
    symbol_id = Column(Integer, ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True, index=True)
    file_path = Column(String(500), nullable=False, index=True)
    code_symbol = Column(String(255), nullable=True, index=True)
    source_revision = Column(String(100), nullable=True)
    chunk_index = Column(Integer, default=0, nullable=False)
    chunk_text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    language = Column(String(50), nullable=True)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    embedding_model = Column(String(100), nullable=True)
    embedding = deferred(Column(Vector(settings.EMBEDDING_DIMENSION), nullable=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repository = relationship("Repository", back_populates="code_chunks")
    file = relationship("IndexedFile", backref="chunks")
    symbol = relationship("CodeSymbol", backref="chunks")

    __table_args__ = (
        UniqueConstraint("repository_id", "file_path", "chunk_index", "content_hash", name="uq_repo_chunk"),
        Index("ix_chunks_repo_hash", "repository_id", "content_hash"),
        Index("ix_chunks_repo_path", "repository_id", "file_path"),
    )
