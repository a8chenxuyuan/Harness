"""003 — plans 表（Phase 23 计划持久化，方案 A）。

Revision ID: 003_plans
Revises: 002_add_indexes
Create Date: 2025-01-03 00:00:00

方案 A：sessions 只存元数据，Plan 单独建表；本迁移只新增 plans 表 + 索引。
"""

from alembic import op
import sqlalchemy as sa


revision = "003_plans"
down_revision = "002_add_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 plans 表（SQLite / PostgreSQL 通用）。"""
    op.create_table(
        "plans",
        sa.Column("plan_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("plan_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("plan_hash", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plans_tenant_id", "plans", ["tenant_id"])
    op.create_index("ix_plans_user_id", "plans", ["user_id"])
    op.create_index(
        "ix_plans_tenant_created", "plans", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    """回退 plans 表。"""
    op.drop_index("ix_plans_tenant_created", table_name="plans")
    op.drop_index("ix_plans_user_id", table_name="plans")
    op.drop_index("ix_plans_tenant_id", table_name="plans")
    op.drop_table("plans")
