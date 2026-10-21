"""009_phase3_incremental_indexing

Revision ID: 009_phase3_incremental_indexing
Revises: 008_add_conversation_summary
Create Date: 2026-10-20 11:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009_phase3_incremental_indexing"
down_revision: Union[str, None] = "008_add_conversation_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    # 1. Add change metrics columns to indexing_jobs
    if dialect_name == "postgresql":
        op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS files_added INTEGER NOT NULL DEFAULT 0")
        op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS files_modified INTEGER NOT NULL DEFAULT 0")
        op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS files_unchanged INTEGER NOT NULL DEFAULT 0")
        op.execute("ALTER TABLE indexing_jobs ADD COLUMN IF NOT EXISTS files_deleted INTEGER NOT NULL DEFAULT 0")
        op.execute("CREATE INDEX IF NOT EXISTS ix_indexed_files_repo_path ON indexed_files (repository_id, path)")
    else:
        try:
            op.add_column("indexing_jobs", sa.Column("files_added", sa.Integer(), nullable=False, server_default="0"))
            op.add_column("indexing_jobs", sa.Column("files_modified", sa.Integer(), nullable=False, server_default="0"))
            op.add_column("indexing_jobs", sa.Column("files_unchanged", sa.Integer(), nullable=False, server_default="0"))
            op.add_column("indexing_jobs", sa.Column("files_deleted", sa.Integer(), nullable=False, server_default="0"))
        except Exception:
            pass

        try:
            op.create_index("ix_indexed_files_repo_path", "indexed_files", ["repository_id", "path"], unique=False)
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_indexed_files_repo_path")
        op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS files_deleted")
        op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS files_unchanged")
        op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS files_modified")
        op.execute("ALTER TABLE indexing_jobs DROP COLUMN IF EXISTS files_added")
    else:
        try:
            op.drop_index("ix_indexed_files_repo_path", table_name="indexed_files")
        except Exception:
            pass
        try:
            op.drop_column("indexing_jobs", "files_deleted")
            op.drop_column("indexing_jobs", "files_unchanged")
            op.drop_column("indexing_jobs", "files_modified")
            op.drop_column("indexing_jobs", "files_added")
        except Exception:
            pass
