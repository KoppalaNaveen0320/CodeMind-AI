"""012_add_github_sync_fields

Revision ID: 012_add_github_sync_fields
Revises: 011_add_user_sessions_and_timeout
Create Date: 2026-10-22 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "012_add_github_sync_fields"
down_revision: Union[str, None] = "011_add_user_sessions_and_timeout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    # 1. Add synchronization tracking columns to repositories table
    if dialect_name == "postgresql":
        op.execute("""
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_synced_commit_sha VARCHAR(100);
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS latest_remote_commit_sha VARCHAR(100);
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_status VARCHAR(50) NOT NULL DEFAULT 'synced';
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS sync_error TEXT;
        """)
    else:
        for col_name, col_type, default in [
            ("last_synced_commit_sha", sa.String(100), None),
            ("latest_remote_commit_sha", sa.String(100), None),
            ("last_checked_at", sa.DateTime(timezone=True), None),
            ("last_synced_at", sa.DateTime(timezone=True), None),
            ("sync_status", sa.String(50), "'synced'"),
            ("sync_error", sa.Text(), None),
        ]:
            try:
                op.add_column(
                    "repositories",
                    sa.Column(col_name, col_type, nullable=True if default is None else False, server_default=sa.text(default) if default else None)
                )
            except Exception:
                pass

    # 2. Create webhook_deliveries table for delivery deduplication
    if dialect_name == "postgresql":
        op.execute("""
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id SERIAL PRIMARY KEY,
                delivery_id VARCHAR(100) NOT NULL UNIQUE,
                event_type VARCHAR(50) NOT NULL,
                repository_id INTEGER REFERENCES repositories(id) ON DELETE CASCADE,
                payload_sha256 VARCHAR(64),
                status VARCHAR(50) NOT NULL DEFAULT 'processed',
                summary TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_delivery_id ON webhook_deliveries(delivery_id);
            CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_repository_id ON webhook_deliveries(repository_id);
        """)
    else:
        try:
            op.create_table(
                "webhook_deliveries",
                sa.Column("id", sa.Integer(), primary_key=True, index=True),
                sa.Column("delivery_id", sa.String(100), unique=True, index=True, nullable=False),
                sa.Column("event_type", sa.String(50), nullable=False),
                sa.Column("repository_id", sa.Integer(), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True, index=True),
                sa.Column("payload_sha256", sa.String(64), nullable=True),
                sa.Column("status", sa.String(50), default="processed", nullable=False),
                sa.Column("summary", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""
    if dialect_name == "postgresql":
        op.execute("DROP TABLE IF EXISTS webhook_deliveries CASCADE;")
        op.execute("""
            ALTER TABLE repositories DROP COLUMN IF EXISTS last_synced_commit_sha;
            ALTER TABLE repositories DROP COLUMN IF EXISTS latest_remote_commit_sha;
            ALTER TABLE repositories DROP COLUMN IF EXISTS last_checked_at;
            ALTER TABLE repositories DROP COLUMN IF EXISTS last_synced_at;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_status;
            ALTER TABLE repositories DROP COLUMN IF EXISTS sync_error;
        """)
    else:
        try:
            op.drop_table("webhook_deliveries")
        except Exception:
            pass
