from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    connected_account_id = Column(Integer, ForeignKey("user_github_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    provider = Column(String(50), default="github", nullable=False)
    is_private = Column(Boolean, default=True, nullable=False)
    default_branch = Column(String(100), default="main", nullable=False)
    primary_language = Column(String(100), nullable=True)
    tech_stack = Column(JSON, nullable=True)
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

    # Synchronization & Auto-Sync Tracking
    last_synced_commit_sha = Column(String(100), nullable=True)
    latest_remote_commit_sha = Column(String(100), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_status = Column(String(50), default="synced", nullable=False) # synced, update_available, syncing, failed, rate_limited
    sync_error = Column(Text, nullable=True)
    sync_error_code = Column(String(100), nullable=True)
    sync_error_category = Column(String(100), nullable=True)
    sync_failed_operation = Column(String(255), nullable=True)
    sync_last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    sync_retry_count = Column(Integer, default=0, nullable=False)
    sync_suggested_action = Column(Text, nullable=True)

    user = relationship("User", backref="repositories")
    connected_account = relationship("UserGitHubAccount", back_populates="repositories")
    indexing_jobs = relationship("IndexingJob", back_populates="repository", cascade="all, delete-orphan")
    indexed_files = relationship("IndexedFile", back_populates="repository", cascade="all, delete-orphan")
    code_symbols = relationship("CodeSymbol", back_populates="repository", cascade="all, delete-orphan")
    code_chunks = relationship("CodeChunk", back_populates="repository", cascade="all, delete-orphan")
    graph_nodes = relationship("GraphNode", back_populates="repository", cascade="all, delete-orphan")
    graph_edges = relationship("GraphEdge", back_populates="repository", cascade="all, delete-orphan")
    webhook_deliveries = relationship("WebhookDelivery", back_populates="repository", cascade="all, delete-orphan")
