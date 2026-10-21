from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class AssistantConversation(Base):
    __tablename__ = "assistant_conversations"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    branch = Column(String(100), nullable=True)
    title = Column(String(255), default="New Conversation", nullable=False)
    title_is_manual = Column(Boolean, default=False, nullable=False, server_default="false")
    summary = Column(Text, nullable=True)
    is_archived = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    repository = relationship("Repository", backref="conversations")
    messages = relationship(
        "AssistantMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.id"
    )

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user", "assistant", "system"
    content = Column(Text, nullable=False)
    citations = Column(Text, nullable=True)  # JSON stringified citations list
    retrieval_strategy = Column(String(50), nullable=True)  # "hybrid", "vector", "keyword", "graph"
    evidence_metadata = Column(Text, nullable=True)  # JSON stringified evidence details
    status = Column(String(20), default="success", nullable=False, server_default="success")  # "success", "failed", "pending"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("AssistantConversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )

