from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from backend.app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    workspace_name = Column(String(255), default="Acme Engineering", nullable=False)
    avatar_initials = Column(String(10), default="AK", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    hashed_password = Column(String(255), nullable=True) # Secure PBKDF2-SHA256 password hash
    
    # GitHub Integration Fields
    github_user_id = Column(String(100), unique=True, index=True, nullable=True)
    github_username = Column(String(100), nullable=True)
    github_access_token = Column(String(500), nullable=True) # Secure server-side storage
    github_token_type = Column(String(50), nullable=True)
    github_scope = Column(String(255), nullable=True)

    # Session & Security Settings
    session_timeout_minutes = Column(Integer, default=30, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
