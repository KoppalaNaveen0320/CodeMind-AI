"""013_add_structured_sync_status

Revision ID: 013_add_structured_sync_status
Revises: 012_add_github_sync_fields
Create Date: 2026-10-24 21:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "013_add_structured_sync_status"
down_revision: Union[str, None] = "012_add_github_sync_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("""
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_error_code VARCHAR(100);
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_error_category VARCHAR(100);
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_failed_operation VARCHAR(255);
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_last_attempt_at TIMESTAMPTZ;
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_retry_count INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_suggested_action TEXT;
        """)
    else:
        for col_name, col_type, default in [
            ("sync_error_code", sa.String(100), None),
            ("sync_error_category", sa.String(100), None),
            ("sync_failed_operation", sa.String(255), None),
            ("sync_last_attempt_at", sa.DateTime(timezone=True), None),
            ("sync_retry_count", sa.Integer(), "0"),
            ("sync_suggested_action", sa.Text(), None),
        ]:
            try:
                op.add_column(
                    "repositories",
                    sa.Column(
                        col_name,
                        col_type,
                        nullable=True if default is None else False,
                        server_default=sa.text(default) if default else None
                    )
                )
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""
    if dialect_name == "postgresql":
        op.execute("""
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_error_code;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_error_category;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_failed_operation;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_last_attempt_at;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_retry_count;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_suggested_action;
        """)
    else:
        for col_name in [
            "sync_error_code",
            "sync_error_category",
            "sync_failed_operation",
            "sync_last_attempt_at",
            "sync_retry_count",
            "sync_suggested_action",
        ]:
            try:
                op.drop_column("repositories", col_name)
            except Exception:
                pass
