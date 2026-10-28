"""
CodeMind AI - User GitHub Account Model
Stores authorized GitHub accounts connected to a CodeMind AI user,
with AES-256-GCM encrypted credentials and rich metadata.
"""

from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base
from backend.app.core.token_encryption import TokenEncryptionService


class UserGitHubAccount(Base):
    __tablename__ = "user_github_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # GitHub Identity
    github_user_id = Column(String(100), nullable=True, index=True)
    github_username = Column(String(100), nullable=False, index=True)
    account_type = Column(String(50), default="user", nullable=False)  # "user" | "organization"
    auth_method = Column(String(50), default="oauth", nullable=False)   # "oauth" | "pat"
    label = Column(String(255), nullable=True)                        # e.g., "Personal PAT", "Acme Org OAuth"
    avatar_url = Column(String(500), nullable=True)

    # AES-256-GCM Encrypted Credentials
    encrypted_token = Column(Text, nullable=False)
    token_nonce = Column(String(100), nullable=False)
    token_tag = Column(String(100), nullable=True)
    key_version = Column(Integer, default=1, nullable=False)

    # Metadata & Permissions
    token_type = Column(String(50), default="bearer", nullable=True)
    token_scope = Column(String(500), nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="github_accounts")
    repositories = relationship("Repository", back_populates="connected_account")

    def get_decrypted_token(self, key_bytes: Optional[bytes] = None) -> str:
        """
        Safely decrypts and returns the raw GitHub token for authorized backend operations.
        Never expose the returned token to frontend APIs or logs.
        """
        return TokenEncryptionService.decrypt_token(
            encrypted_token_b64=self.encrypted_token,
            nonce_b64=self.token_nonce,
            key_bytes=key_bytes
        )

    def set_encrypted_token(self, plain_token: str, key_bytes: Optional[bytes] = None, key_version: int = 1) -> None:
        """
        Encrypts a plaintext token with AES-256-GCM and stores ciphertext, nonce, and tag.
        """
        enc_res = TokenEncryptionService.encrypt_token(
            plain_token=plain_token,
            key_bytes=key_bytes,
            key_version=key_version
        )
        self.encrypted_token = enc_res["encrypted_token"]
        self.token_nonce = enc_res["nonce"]
        self.token_tag = enc_res["tag"]
        self.key_version = enc_res["key_version"]

    def to_safe_dict(self) -> dict:
        """
        Serializes safe, non-sensitive account metadata for frontend consumption.
        NEVER includes tokens, nonces, or tags.
        """
        return {
            "id": self.id,
            "user_id": self.user_id,
            "github_user_id": self.github_user_id,
            "github_username": self.github_username,
            "account_type": self.account_type,
            "auth_method": self.auth_method,
            "label": self.label or f"@{self.github_username} ({self.auth_method.upper()})",
            "avatar_url": self.avatar_url,
            "token_scope": self.token_scope,
            "token_type": self.token_type,
            "token_expires_at": self.token_expires_at,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
