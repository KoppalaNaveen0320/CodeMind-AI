"""005_add_hashed_password_to_users

Revision ID: 005_add_hashed_password_to_users
Revises: 004_update_embedding_dimension_768
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_add_hashed_password_to_users"
down_revision: Union[str, None] = "004_update_embedding_dimension_768"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255)")
    else:
        # SQLite / other test databases
        try:
            op.add_column("users", sa.Column("hashed_password", sa.String(255), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS hashed_password")
    else:
        try:
            op.drop_column("users", "hashed_password")
        except Exception:
            pass
