"""002 — 额外索引 + 唯一约束（性能调优，Phase 24）。

Revision ID: 002_add_indexes
Revises: 001_initial_tables
Create Date: 2025-01-02 00:00:00

只加索引和 unique constraint，不改表结构。
"""

from alembic import op
import sqlalchemy as sa


revision = "002_add_indexes"
down_revision = "001_initial_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users: (tenant_id, username) 应该唯一
    # SQLite 不支持 ALTER TABLE ADD CONSTRAINT，必须走 batch 模式重建表
    with op.batch_alter_table("users") as batch:
        batch.create_unique_constraint(
            "uq_users_tenant_username",
            ["tenant_id", "username"],
        )

    # audit_logs: 复合索引（tenant + action + time 范围查询）
    op.create_index(
        "ix_audit_logs_tenant_action_time",
        "audit_logs",
        ["tenant_id", "action", "created_at"],
    )

    # sessions: (tenant_id, user_id, status) 复合
    op.create_index(
        "ix_sessions_tenant_user",
        "sessions",
        ["tenant_id", "user_id"],
    )

    # memories: content 全文搜索可以后续加 GIN / pg_trgm
    # SQLite 阶段先不加


def downgrade() -> None:
    op.drop_index("ix_sessions_tenant_user", table_name="sessions")
    op.drop_index("ix_audit_logs_tenant_action_time", table_name="audit_logs")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_tenant_username", type_="unique")
