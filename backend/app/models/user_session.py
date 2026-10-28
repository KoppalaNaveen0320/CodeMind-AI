from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from backend.app.db.session import Base


class UserSession(Base):
    """
    Persistent active sessions and security audit model.
    Tracks client device/browser, IP address, login/logout timestamps,
    expiration boundary, current accessed path, and revocation status.
    """
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash = Column(String(64), unique=True, index=True, nullable=False)
    device_label = Column(String(255), nullable=False)
    browser = Column(String(100), nullable=True)
    os = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    login_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    last_activity_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    logout_at = Column(DateTime(timezone=True), nullable=True)
    last_accessed_path = Column(String(255), default="/dashboard", nullable=False)
    status = Column(String(20), default="active", nullable=False, index=True)  # active, expired, logged_out, revoked

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", backref="sessions")

    def is_active(self) -> bool:
        if self.status != "active":
            return False
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now < exp
