from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    provider = Column(String(50), default="github", nullable=False)
    is_private = Column(Boolean, default=True, nullable=False)
    default_branch = Column(String(100), default="main", nullable=False)
    primary_language = Column(String(100), nullable=True)
    status = Column(String(50), default="ready", nullable=False)  # ready, indexing, pending, failed
    
    # GitHub Integration metadata
    github_repo_id = Column(BigInteger, nullable=True, index=True)
    html_url = Column(String(255), nullable=True)
    clone_url = Column(String(255), nullable=True)
    owner_login = Column(String(100), nullable=True)
    current_revision = Column(String(100), nullable=True) # Commit SHA of latest indexed revision

    # Metrics
    files_count = Column(Integer, default=0, nullable=False)
    symbols_count = Column(Integer, default=0, nullable=False)
    apis_count = Column(Integer, default=0, nullable=False)
    dependencies_count = Column(Integer, default=0, nullable=False)
    last_indexed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    indexing_jobs = relationship("IndexingJob", back_populates="repository", cascade="all, delete-orphan")
    indexed_files = relationship("IndexedFile", back_populates="repository", cascade="all, delete-orphan")
    code_symbols = relationship("CodeSymbol", back_populates="repository", cascade="all, delete-orphan")
    code_chunks = relationship("CodeChunk", back_populates="repository", cascade="all, delete-orphan")
    graph_nodes = relationship("GraphNode", back_populates="repository", cascade="all, delete-orphan")
    graph_edges = relationship("GraphEdge", back_populates="repository", cascade="all, delete-orphan")
