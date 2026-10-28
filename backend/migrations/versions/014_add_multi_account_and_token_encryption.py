"""014_add_multi_account_and_token_encryption

Revision ID: 014_add_multi_account_and_token_encryption
Revises: 013_add_structured_sync_status
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
from datetime import datetime, timezone

from backend.app.core.token_encryption import TokenEncryptionService

revision: str = "014_add_multi_account_and_token_encryption"
down_revision: Union[str, None] = "013_add_structured_sync_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    # 1. Create user_github_accounts table
    if dialect_name == "postgresql":
        op.execute("""
            CREATE TABLE IF NOT EXISTS user_github_accounts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                github_user_id VARCHAR(100),
                github_username VARCHAR(100) NOT NULL,
                account_type VARCHAR(50) NOT NULL DEFAULT 'user',
                auth_method VARCHAR(50) NOT NULL DEFAULT 'oauth',
                label VARCHAR(255),
                avatar_url VARCHAR(500),
                encrypted_token TEXT NOT NULL,
                token_nonce VARCHAR(100) NOT NULL,
                token_tag VARCHAR(100),
                key_version INTEGER NOT NULL DEFAULT 1,
                token_type VARCHAR(50) DEFAULT 'bearer',
                token_scope VARCHAR(500),
                token_expires_at TIMESTAMPTZ,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS ix_user_github_accounts_user_id ON user_github_accounts(user_id);
            CREATE INDEX IF NOT EXISTS ix_user_github_accounts_github_username ON user_github_accounts(github_username);
            CREATE INDEX IF NOT EXISTS ix_user_github_accounts_github_user_id ON user_github_accounts(github_user_id);
        """)
        op.execute("""
            ALTER TABLE repositories ADD COLUMN IF NOT EXISTS connected_account_id INTEGER REFERENCES user_github_accounts(id) ON DELETE SET NULL;
            CREATE INDEX IF NOT EXISTS ix_repositories_connected_account_id ON repositories(connected_account_id);
        """)
    else:
        # SQLite
        try:
            op.create_table(
                "user_github_accounts",
                sa.Column("id", sa.Integer(), primary_key=True, index=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
                sa.Column("github_user_id", sa.String(100), nullable=True, index=True),
                sa.Column("github_username", sa.String(100), nullable=False, index=True),
                sa.Column("account_type", sa.String(50), nullable=False, server_default="user"),
                sa.Column("auth_method", sa.String(50), nullable=False, server_default="oauth"),
                sa.Column("label", sa.String(255), nullable=True),
                sa.Column("avatar_url", sa.String(500), nullable=True),
                sa.Column("encrypted_token", sa.Text(), nullable=False),
                sa.Column("token_nonce", sa.String(100), nullable=False),
                sa.Column("token_tag", sa.String(100), nullable=True),
                sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
                sa.Column("token_type", sa.String(50), nullable=True, server_default="bearer"),
                sa.Column("token_scope", sa.String(500), nullable=True),
                sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )
        except Exception:
            pass

        try:
            op.add_column(
                "repositories",
                sa.Column(
                    "connected_account_id",
                    sa.Integer(),
                    sa.ForeignKey("user_github_accounts.id", ondelete="SET NULL"),
                    nullable=True,
                    index=True
                )
            )
        except Exception:
            pass

    # 2. Data Migration: Migrate existing plaintext tokens in users table to user_github_accounts
    try:
        users = bind.execute(text("SELECT id, github_access_token, github_username, github_user_id, github_token_type, github_scope FROM users WHERE github_access_token IS NOT NULL")).fetchall()
        for u in users:
            u_id, raw_token, gh_uname, gh_uid, token_type, scope = u[0], u[1], u[2], u[3], u[4], u[5]
            if raw_token:
                try:
                    enc_data = TokenEncryptionService.encrypt_token(raw_token)
                    uname = gh_uname or f"user_{u_id}"
                    
                    if dialect_name == "postgresql":
                        res = bind.execute(text("""
                            INSERT INTO user_github_accounts (
                                user_id, github_user_id, github_username, account_type, auth_method,
                                encrypted_token, token_nonce, token_tag, key_version,
                                token_type, token_scope, is_active, created_at
                            ) VALUES (
                                :user_id, :github_user_id, :github_username, 'user', 'oauth',
                                :enc_token, :nonce, :tag, :kver,
                                :token_type, :scope, TRUE, CURRENT_TIMESTAMP
                            ) RETURNING id
                        """), {
                            "user_id": u_id,
                            "github_user_id": str(gh_uid) if gh_uid else None,
                            "github_username": uname,
                            "enc_token": enc_data["encrypted_token"],
                            "nonce": enc_data["nonce"],
                            "tag": enc_data["tag"],
                            "kver": enc_data["key_version"],
                            "token_type": token_type or "bearer",
                            "scope": scope
                        })
                        acc_id = res.scalar()
                    else:
                        bind.execute(text("""
                            INSERT INTO user_github_accounts (
                                user_id, github_user_id, github_username, account_type, auth_method,
                                encrypted_token, token_nonce, token_tag, key_version,
                                token_type, token_scope, is_active, created_at
                            ) VALUES (
                                :user_id, :github_user_id, :github_username, 'user', 'oauth',
                                :enc_token, :nonce, :tag, :kver,
                                :token_type, :scope, 1, CURRENT_TIMESTAMP
                            )
                        """), {
                            "user_id": u_id,
                            "github_user_id": str(gh_uid) if gh_uid else None,
                            "github_username": uname,
                            "enc_token": enc_data["encrypted_token"],
                            "nonce": enc_data["nonce"],
                            "tag": enc_data["tag"],
                            "kver": enc_data["key_version"],
                            "token_type": token_type or "bearer",
                            "scope": scope
                        })
                        acc_id = bind.execute(text("SELECT last_insert_rowid()")).scalar()

                    # Associate existing repositories of this user to the newly created account
                    if acc_id:
                        bind.execute(text("""
                            UPDATE repositories 
                            SET connected_account_id = :acc_id 
                            WHERE user_id = :user_id AND connected_account_id IS NULL
                        """), {"acc_id": acc_id, "user_id": u_id})

                except Exception as enc_err:
                    print(f"Warning: could not migrate token for user {u_id}: {enc_err}")
    except Exception as e:
        print(f"Notice: skipped plaintext user token migration: {e}")


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else ""

    if dialect_name == "postgresql":
        op.execute("ALTER TABLE repositories DROP COLUMN IF EXISTS connected_account_id;")
        op.execute("DROP TABLE IF EXISTS user_github_accounts CASCADE;")
    else:
        try:
            op.drop_column("repositories", "connected_account_id")
        except Exception:
            pass
        try:
            op.drop_table("user_github_accounts")
        except Exception:
            pass
