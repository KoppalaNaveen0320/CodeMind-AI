"""003_hybrid_rag_and_knowledge_graph

Revision ID: 003_hybrid_rag_and_knowledge_graph
Revises: 002_github_and_indexing_schema
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "003_hybrid_rag_and_knowledge_graph"
down_revision: Union[str, None] = "002_github_and_indexing_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    # Enable pgvector extension if on PostgreSQL
    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")

    # 1. Create code_chunks table
    op.create_table(
        "code_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("indexed_files.id", ondelete="CASCADE"), nullable=True),
        sa.Column("symbol_id", sa.Integer(), sa.ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("code_symbol", sa.String(length=255), nullable=True),
        sa.Column("source_revision", sa.String(length=100), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("repository_id", "file_path", "chunk_index", "content_hash", name="uq_repo_chunk"),
    )
    op.create_index(op.f("ix_code_chunks_repository_id"), "code_chunks", ["repository_id"], unique=False)
    op.create_index(op.f("ix_code_chunks_file_id"), "code_chunks", ["file_id"], unique=False)
    op.create_index(op.f("ix_code_chunks_symbol_id"), "code_chunks", ["symbol_id"], unique=False)
    op.create_index(op.f("ix_code_chunks_file_path"), "code_chunks", ["file_path"], unique=False)
    op.create_index(op.f("ix_code_chunks_code_symbol"), "code_chunks", ["code_symbol"], unique=False)
    op.create_index(op.f("ix_code_chunks_content_hash"), "code_chunks", ["content_hash"], unique=False)
    op.create_index("ix_chunks_repo_hash", "code_chunks", ["repository_id", "content_hash"], unique=False)
    op.create_index("ix_chunks_repo_path", "code_chunks", ["repository_id", "file_path"], unique=False)

    # Vector similarity index for PostgreSQL
    if dialect_name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_cosine ON code_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )

    # 2. Create graph_nodes table
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_key", sa.String(length=500), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("source_revision", sa.String(length=100), nullable=True),
        sa.Column("properties", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("repository_id", "node_key", name="uq_repo_node_key"),
    )
    op.create_index(op.f("ix_graph_nodes_repository_id"), "graph_nodes", ["repository_id"], unique=False)
    op.create_index(op.f("ix_graph_nodes_node_key"), "graph_nodes", ["node_key"], unique=False)
    op.create_index(op.f("ix_graph_nodes_node_type"), "graph_nodes", ["node_type"], unique=False)
    op.create_index(op.f("ix_graph_nodes_name"), "graph_nodes", ["name"], unique=False)
    op.create_index(op.f("ix_graph_nodes_file_path"), "graph_nodes", ["file_path"], unique=False)
    op.create_index(op.f("ix_graph_nodes_symbol_name"), "graph_nodes", ["symbol_name"], unique=False)
    op.create_index("ix_graph_nodes_repo_type", "graph_nodes", ["repository_id", "node_type"], unique=False)
    op.create_index("ix_graph_nodes_repo_path", "graph_nodes", ["repository_id", "file_path"], unique=False)

    # 3. Create graph_edges table
    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.Integer(), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.Integer(), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("edge_type", sa.String(length=50), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_revision", sa.String(length=100), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("repository_id", "source_node_id", "target_node_id", "edge_type", name="uq_repo_edge"),
    )
    op.create_index(op.f("ix_graph_edges_repository_id"), "graph_edges", ["repository_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_source_node_id"), "graph_edges", ["source_node_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_target_node_id"), "graph_edges", ["target_node_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_edge_type"), "graph_edges", ["edge_type"], unique=False)
    op.create_index("ix_graph_edges_source_type", "graph_edges", ["source_node_id", "edge_type"], unique=False)
    op.create_index("ix_graph_edges_target_type", "graph_edges", ["target_node_id", "edge_type"], unique=False)
    op.create_index("ix_graph_edges_repo_type", "graph_edges", ["repository_id", "edge_type"], unique=False)

    # 4. Create assistant_conversations table
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New Conversation"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index(op.f("ix_assistant_conversations_repository_id"), "assistant_conversations", ["repository_id"], unique=False)
    op.create_index(op.f("ix_assistant_conversations_user_id"), "assistant_conversations", ["user_id"], unique=False)

    # 5. Create assistant_messages table
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("retrieval_strategy", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_assistant_messages_conversation_id"), "assistant_messages", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_table("assistant_messages")
    op.drop_table("assistant_conversations")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("code_chunks")
