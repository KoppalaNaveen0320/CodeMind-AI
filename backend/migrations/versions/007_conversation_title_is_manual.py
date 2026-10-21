"""007_conversation_title_is_manual

Revision ID: 007_conversation_title_is_manual
Revises: 006_chat_history_enhancements
Create Date: 2026-10-18 17:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007_conversation_title_is_manual"
down_revision: Union[str, None] = "006_chat_history_enhancements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE assistant_conversations ADD COLUMN IF NOT EXISTS title_is_manual BOOLEAN NOT NULL DEFAULT false")
    else:
        try:
            op.add_column("assistant_conversations", sa.Column("title_is_manual", sa.Boolean(), nullable=False, server_default=sa.false()))
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE assistant_conversations DROP COLUMN IF EXISTS title_is_manual")
    else:
        try:
            op.drop_column("assistant_conversations", "title_is_manual")
        except Exception:
            pass
