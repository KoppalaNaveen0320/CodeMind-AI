"""008_add_conversation_summary

Revision ID: 008_add_conversation_summary
Revises: 007_conversation_title_is_manual
Create Date: 2026-10-19 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008_add_conversation_summary"
down_revision: Union[str, None] = "007_conversation_title_is_manual"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE assistant_conversations ADD COLUMN IF NOT EXISTS summary TEXT")
    else:
        try:
            op.add_column("assistant_conversations", sa.Column("summary", sa.Text(), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE assistant_conversations DROP COLUMN IF EXISTS summary")
    else:
        try:
            op.drop_column("assistant_conversations", "summary")
        except Exception:
            pass
