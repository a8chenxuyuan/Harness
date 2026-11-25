"""005 — pgvector 可选增强（Phase 24）。

Revision ID: 005_pgvector_optional
Revises: 004_session_entries
Create Date: 2025-01-05 00:00:00

仅当数据库是 PostgreSQL 时执行：
    - CREATE EXTENSION IF NOT EXISTS vector
    - ALTER TABLE memories ADD COLUMN embedding vector(1536)
    - 建立 hnsw 余弦索引

SQLite 环境（开发/测试）直接跳过，不报错。
注意：向量维度 1536 以 OpenAI text-embedding-3-small 为基准，
换模型需自行调整迁移或改用无维度限制的列。
"""

from alembic import op
import sqlalchemy as sa


revision = "005_pgvector_optional"
down_revision = "004_session_entries"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    """当前连接是否为 PostgreSQL。"""
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """PostgreSQL 下启用 pgvector；其他后端跳过。"""
    if not _is_postgres():
        return
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(
        sa.text("ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(1536)")
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw "
            "ON memories USING hnsw (embedding vector_cosine_ops)"
        )
    )


def downgrade() -> None:
    """仅 PostgreSQL 下回退向量列与索引。"""
    if not _is_postgres():
        return
    op.execute(sa.text("DROP INDEX IF EXISTS ix_memories_embedding_hnsw"))
    op.execute(sa.text("ALTER TABLE memories DROP COLUMN IF EXISTS embedding"))
