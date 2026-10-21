"""006_chat_history_enhancements

Revision ID: 006_chat_history_enhancements
Revises: 005_add_hashed_password_to_users
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006_chat_history_enhancements"
down_revision: Union[str, None] = "005_add_hashed_password_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        # 1. Update assistant_conversations
        op.execute("ALTER TABLE assistant_conversations ADD COLUMN IF NOT EXISTS branch VARCHAR(100)")
        op.execute("ALTER TABLE assistant_conversations ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false")
        op.execute("ALTER TABLE assistant_conversations ALTER COLUMN repository_id DROP NOT NULL")
        op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_user_updated ON assistant_conversations (user_id, updated_at DESC)")

        # 2. Update assistant_messages
        op.execute("ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS evidence_metadata TEXT")
        op.execute("ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'success'")
        op.execute("CREATE INDEX IF NOT EXISTS ix_messages_conv_created ON assistant_messages (conversation_id, created_at ASC)")
    else:
        # SQLite / other fallback
        try:
            op.add_column("assistant_conversations", sa.Column("branch", sa.String(100), nullable=True))
        except Exception:
            pass
        try:
            op.add_column("assistant_conversations", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
        except Exception:
            pass
        try:
            op.add_column("assistant_messages", sa.Column("evidence_metadata", sa.Text(), nullable=True))
        except Exception:
            pass
        try:
            op.add_column("assistant_messages", sa.Column("status", sa.String(20), nullable=False, server_default="success"))
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_messages_conv_created")
        op.execute("ALTER TABLE assistant_messages DROP COLUMN IF EXISTS status")
        op.execute("ALTER TABLE assistant_messages DROP COLUMN IF EXISTS evidence_metadata")

        op.execute("DROP INDEX IF EXISTS ix_conversations_user_updated")
        op.execute("ALTER TABLE assistant_conversations DROP COLUMN IF EXISTS is_archived")
        op.execute("ALTER TABLE assistant_conversations DROP COLUMN IF EXISTS branch")
    else:
        try:
            op.drop_column("assistant_messages", "status")
            op.drop_column("assistant_messages", "evidence_metadata")
            op.drop_column("assistant_conversations", "is_archived")
            op.drop_column("assistant_conversations", "branch")
        except Exception:
            pass
