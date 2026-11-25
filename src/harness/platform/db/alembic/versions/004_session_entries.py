"""004 — session_entries 表（Phase 24 方案 A）。

Revision ID: 004_session_entries
Revises: 003_plans
Create Date: 2025-01-04 00:00:00

append-only 会话历史：sessions 表只存元数据，会话消息逐条追加到这里，
恢复时按 seq ASC 重放。
"""

from alembic import op
import sqlalchemy as sa


revision = "004_session_entries"
down_revision = "003_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 append-only 会话历史表（SQLite / PostgreSQL 通用）。"""
    op.create_table(
        "session_entries",
        sa.Column("entry_id", sa.String(length=64), primary_key=True),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_session_entries_seq", "session_entries", ["seq"])
    op.create_index("ix_session_entries_kind", "session_entries", ["kind"])


def downgrade() -> None:
    """回退 session_entries 表。"""
    op.drop_index("ix_session_entries_kind", table_name="session_entries")
    op.drop_index("ix_session_entries_seq", table_name="session_entries")
    op.drop_table("session_entries")
