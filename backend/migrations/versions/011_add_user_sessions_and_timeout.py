"""011_add_user_sessions_and_timeout

Revision ID: 011_add_user_sessions_and_timeout
Revises: 010_add_tech_stack_to_repositories
Create Date: 2026-10-22 18:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "011_add_user_sessions_and_timeout"
down_revision: Union[str, None] = "010_add_tech_stack_to_repositories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    # 1. Add session_timeout_minutes to users table
    if dialect_name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_timeout_minutes INTEGER NOT NULL DEFAULT 30")
    else:
        try:
            op.add_column("users", sa.Column("session_timeout_minutes", sa.Integer(), nullable=False, server_default="30"))
        except Exception:
            pass

    # 2. Create user_sessions table
    if dialect_name == "postgresql":
        op.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_token_hash VARCHAR(64) NOT NULL UNIQUE,
                device_label VARCHAR(255) NOT NULL,
                browser VARCHAR(100),
                os VARCHAR(100),
                ip_address VARCHAR(45),
                login_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                logout_at TIMESTAMPTZ,
                last_accessed_path VARCHAR(255) NOT NULL DEFAULT '/dashboard',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS ix_user_sessions_session_token_hash ON user_sessions(session_token_hash);
            CREATE INDEX IF NOT EXISTS ix_user_sessions_status ON user_sessions(status);
            CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions(expires_at);
        """)
    else:
        try:
            op.create_table(
                "user_sessions",
                sa.Column("id", sa.Integer(), primary_key=True, index=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
                sa.Column("session_token_hash", sa.String(length=64), unique=True, index=True, nullable=False),
                sa.Column("device_label", sa.String(length=255), nullable=False),
                sa.Column("browser", sa.String(length=100), nullable=True),
                sa.Column("os", sa.String(length=100), nullable=True),
                sa.Column("ip_address", sa.String(length=45), nullable=True),
                sa.Column("login_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
                sa.Column("logout_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("last_accessed_path", sa.String(length=255), nullable=False, server_default="/dashboard"),
                sa.Column("status", sa.String(length=20), nullable=False, server_default="active", index=True),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("DROP TABLE IF EXISTS user_sessions CASCADE")
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS session_timeout_minutes")
    else:
        try:
            op.drop_table("user_sessions")
        except Exception:
            pass
        try:
            op.drop_column("users", "session_timeout_minutes")
        except Exception:
            pass
