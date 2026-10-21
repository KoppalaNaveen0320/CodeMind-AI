"""001_initial_schema

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-10-15 21:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('workspace_name', sa.String(length=255), nullable=False, server_default='Acme Engineering'),
        sa.Column('avatar_initials', sa.String(length=10), nullable=False, server_default='AK'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)


    # Repositories table
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='github'),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('default_branch', sa.String(length=100), nullable=False, server_default='main'),
        sa.Column('primary_language', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='ready'),
        sa.Column('files_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('symbols_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('apis_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dependencies_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_repositories_name'), 'repositories', ['name'], unique=False)
    op.create_index(op.f('ix_repositories_full_name'), 'repositories', ['full_name'], unique=True)

    # Indexing Jobs table
    op.create_table(
        'indexing_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('repository_id', sa.Integer(), sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_indexing_jobs_repository_id'), 'indexing_jobs', ['repository_id'], unique=False)


def downgrade() -> None:
    op.drop_table('indexing_jobs')
    op.drop_table('repositories')
    op.drop_table('users')
