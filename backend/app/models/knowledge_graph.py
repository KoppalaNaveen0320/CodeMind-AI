from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.db.session import Base


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    node_key = Column(String(500), nullable=False, index=True)
    node_type = Column(String(50), nullable=False, index=True) # repository, file, module, function, class, method, import, dependency
    name = Column(String(255), nullable=False, index=True)
    file_path = Column(String(500), nullable=True, index=True)
    symbol_name = Column(String(255), nullable=True, index=True)
    signature = Column(Text, nullable=True)
    start_line = Column(Integer, nullable=True)
    end_line = Column(Integer, nullable=True)
    language = Column(String(50), nullable=True)
    source_revision = Column(String(100), nullable=True)
    properties = Column(Text, nullable=True) # JSON-serialized extra attributes
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repository = relationship("Repository", back_populates="graph_nodes")
    outgoing_edges = relationship(
        "GraphEdge",
        foreign_keys="[GraphEdge.source_node_id]",
        back_populates="source_node",
        cascade="all, delete-orphan"
    )
    incoming_edges = relationship(
        "GraphEdge",
        foreign_keys="[GraphEdge.target_node_id]",
        back_populates="target_node",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("repository_id", "node_key", name="uq_repo_node_key"),
        Index("ix_graph_nodes_repo_type", "repository_id", "node_type"),
        Index("ix_graph_nodes_repo_path", "repository_id", "file_path"),
    )


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(Integer, ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(String(50), nullable=False, index=True) # CONTAINS, DEFINES, IMPORTS, CALLS, DEPENDS_ON, REFERENCES
    is_verified = Column(Boolean, default=True, nullable=False) # True = verified static analysis, False = inferred
    source_revision = Column(String(100), nullable=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    repository = relationship("Repository", back_populates="graph_edges")
    source_node = relationship("GraphNode", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("GraphNode", foreign_keys=[target_node_id], back_populates="incoming_edges")

    __table_args__ = (
        UniqueConstraint("repository_id", "source_node_id", "target_node_id", "edge_type", name="uq_repo_edge"),
        Index("ix_graph_edges_source_type", "source_node_id", "edge_type"),
        Index("ix_graph_edges_target_type", "target_node_id", "edge_type"),
        Index("ix_graph_edges_repo_type", "repository_id", "edge_type"),
    )
