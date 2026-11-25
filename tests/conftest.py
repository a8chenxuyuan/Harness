"""pytest 公共夹具。

隔离策略：
    - JWT 密钥 / 开发模式在 import harness 之前固定，避免读到 .env 的生产配置；
    - 每个用例一个临时 SQLite 文件（覆盖 HARNESS_DATABASE_URL），用完释放引擎，
      防止连接池跨事件循环复用；
    - FastAPI 应用整个测试会话复用（create_app 本身不访问数据库）。
"""

from __future__ import annotations

import os

# 必须在 import harness 之前设置
os.environ["HARNESS_DEV_MODE"] = "0"
os.environ["HARNESS_JWT_SECRET"] = "test-secret-0123456789abcdef0123456789"

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from harness.app import create_app


@pytest.fixture(scope="session")
def app():
    """整个测试会话共用一个 FastAPI 应用实例。"""
    return create_app()


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    """每个用例独立 SQLite 库；用例结束 dispose 引擎。"""
    from harness.platform.infra.engine import close_db, init_db

    db_file = tmp_path / "harness_test.db"
    monkeypatch.setenv(
        "HARNESS_DATABASE_URL", f"sqlite+aiosqlite:///{db_file.as_posix()}"
    )
    await init_db()
    yield
    await close_db()


@pytest.fixture
async def client(app):
    """ASGI 直连客户端（lifespan 不启动，建库由 _isolated_db 负责）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def register_user(client):
    """注册一个随机用户，返回 (username, password, 响应 data)。"""

    async def _register() -> tuple[str, str, dict]:
        username = f"user_{uuid.uuid4().hex[:8]}"
        password = "Passw0rd!2026"
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
            },
        )
        assert resp.status_code == 200, resp.text
        return username, password, resp.json()["data"]

    return _register


@pytest.fixture
async def auth_headers(register_user):
    """注册并返回 Bearer 认证头。"""
    _, _, data = await register_user()
    return {"Authorization": f"Bearer {data['access_token']}"}
