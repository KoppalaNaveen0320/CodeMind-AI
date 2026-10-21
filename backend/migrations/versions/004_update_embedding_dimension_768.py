"""004_update_embedding_dimension_768

Revision ID: 004_update_embedding_dimension_768
Revises: 003_hybrid_rag_and_knowledge_graph
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "004_update_embedding_dimension_768"
down_revision: Union[str, None] = "003_hybrid_rag_and_knowledge_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        # 1. Safely drop existing HNSW cosine index before altering vector dimension
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_cosine")

        # 2. Invalidate incompatible historical vectors so they cannot be corrupted or used for semantic search
        op.execute("UPDATE code_chunks SET embedding = NULL, embedding_model = NULL WHERE embedding IS NOT NULL")

        # 3. Alter vector column to 768 dimensions (for local nomic-embed-text)
        op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(768)")

        # 4. Recreate HNSW cosine similarity index for vector(768)
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_cosine ON code_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_cosine")
        op.execute("UPDATE code_chunks SET embedding = NULL, embedding_model = NULL WHERE embedding IS NOT NULL")
        op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(1536)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_cosine ON code_chunks "
            "USING hnsw (embedding vector_cosine_ops)"
        )
