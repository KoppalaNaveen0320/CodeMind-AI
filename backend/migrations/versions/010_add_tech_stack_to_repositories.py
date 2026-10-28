"""010_add_tech_stack_to_repositories

Revision ID: 010_add_tech_stack_to_repositories
Revises: 009_phase3_incremental_indexing
Create Date: 2026-10-21 21:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "010_add_tech_stack_to_repositories"
down_revision: Union[str, None] = "009_phase3_incremental_indexing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE repositories ADD COLUMN IF NOT EXISTS tech_stack JSON")
    else:
        try:
            op.add_column("repositories", sa.Column("tech_stack", sa.JSON(), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE repositories DROP COLUMN IF EXISTS tech_stack")
    else:
        try:
            op.drop_column("repositories", "tech_stack")
        except Exception:
            pass
