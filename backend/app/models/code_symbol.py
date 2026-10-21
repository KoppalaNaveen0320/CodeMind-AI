from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class CodeSymbol(Base):
    __tablename__ = "code_symbols"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("indexed_files.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    kind = Column(String(50), nullable=False, index=True) # function, class, method, import
    signature = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    start_column = Column(Integer, default=0, nullable=False)
    end_column = Column(Integer, default=0, nullable=False)
    docstring = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repository = relationship("Repository", back_populates="code_symbols")
    file = relationship("IndexedFile", back_populates="symbols")

    __table_args__ = (
        Index("ix_code_symbols_repo_name", "repository_id", "name"),
        Index("ix_code_symbols_repo_kind", "repository_id", "kind"),
    )
