"""002_github_and_indexing_schema

Revision ID: 002_github_and_indexing_schema
Revises: 001_initial_schema
Create Date: 2026-10-15 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_github_and_indexing_schema'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update users table with GitHub OAuth fields
    op.add_column('users', sa.Column('github_user_id', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('github_username', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('github_access_token', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('github_token_type', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('github_scope', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_users_github_user_id'), 'users', ['github_user_id'], unique=True)

    # 2. Create oauth_states table
    op.create_table(
        'oauth_states',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('state', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_oauth_states_state'), 'oauth_states', ['state'], unique=True)

    # 3. Update repositories table with GitHub metadata and revision tracking
    op.add_column('repositories', sa.Column('user_id', sa.Integer(), nullable=True))
    op.add_column('repositories', sa.Column('github_repo_id', sa.BigInteger(), nullable=True))
    op.add_column('repositories', sa.Column('html_url', sa.String(length=255), nullable=True))
    op.add_column('repositories', sa.Column('clone_url', sa.String(length=255), nullable=True))
    op.add_column('repositories', sa.Column('owner_login', sa.String(length=100), nullable=True))
    op.add_column('repositories', sa.Column('current_revision', sa.String(length=100), nullable=True))
    op.create_foreign_key('fk_repositories_user_id', 'repositories', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_repositories_github_repo_id'), 'repositories', ['github_repo_id'], unique=False)
    op.create_index(op.f('ix_repositories_user_id'), 'repositories', ['user_id'], unique=False)

    # 4. Update indexing_jobs with stage, branch, commit_sha
    op.add_column('indexing_jobs', sa.Column('stage', sa.String(length=50), nullable=False, server_default='QUEUED'))
    op.add_column('indexing_jobs', sa.Column('branch', sa.String(length=100), nullable=False, server_default='main'))
    op.add_column('indexing_jobs', sa.Column('commit_sha', sa.String(length=100), nullable=True))

    # 5. Create indexed_files table
    op.create_table(
        'indexed_files',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('language', sa.String(length=50), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('lines_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_indexed_files_path'), 'indexed_files', ['path'], unique=False)
    op.create_index(op.f('ix_indexed_files_repository_id'), 'indexed_files', ['repository_id'], unique=False)

    # 6. Create code_symbols table
    op.create_table(
        'code_symbols',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('indexed_files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=50), nullable=False),
        sa.Column('signature', sa.Text(), nullable=True),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('start_column', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('end_column', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('docstring', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(op.f('ix_code_symbols_file_id'), 'code_symbols', ['file_id'], unique=False)
    op.create_index(op.f('ix_code_symbols_kind'), 'code_symbols', ['kind'], unique=False)
    op.create_index(op.f('ix_code_symbols_name'), 'code_symbols', ['name'], unique=False)
    op.create_index(op.f('ix_code_symbols_repository_id'), 'code_symbols', ['repository_id'], unique=False)


def downgrade() -> None:
    op.drop_table('code_symbols')
    op.drop_table('indexed_files')
    op.drop_column('indexing_jobs', 'commit_sha')
    op.drop_column('indexing_jobs', 'branch')
    op.drop_column('indexing_jobs', 'stage')
    op.drop_index(op.f('ix_repositories_user_id'), table_name='repositories')
    op.drop_index(op.f('ix_repositories_github_repo_id'), table_name='repositories')
    op.drop_column('repositories', 'current_revision')
    op.drop_column('repositories', 'owner_login')
    op.drop_column('repositories', 'clone_url')
    op.drop_column('repositories', 'html_url')
    op.drop_column('repositories', 'github_repo_id')
    op.drop_constraint('fk_repositories_user_id', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'user_id')
    op.drop_table('oauth_states')
    op.drop_index(op.f('ix_users_github_user_id'), table_name='users')
    op.drop_column('users', 'github_scope')
    op.drop_column('users', 'github_token_type')
    op.drop_column('users', 'github_access_token')
    op.drop_column('users', 'github_username')
    op.drop_column('users', 'github_user_id')
