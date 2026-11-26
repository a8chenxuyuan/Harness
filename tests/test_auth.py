"""认证接口集成测试（注册 / 登录 / 刷新 / me / 鉴权失败）。"""

from __future__ import annotations

from httpx import AsyncClient

REGISTER_PATH = "/api/v1/auth/register"
LOGIN_PATH = "/api/v1/auth/login"
REFRESH_PATH = "/api/v1/auth/refresh"
ME_PATH = "/api/v1/auth/me"


async def test_register_login_and_me(client: AsyncClient, register_user) -> None:
    """注册 → me → 登录，全链路 token 可用。"""
    username, password, data = await register_user()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["expires_in"] > 0

    me = await client.get(
        ME_PATH, headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    body = me.json()
    assert body["code"] == 0
    assert body["data"]["role"] == "member"
    assert body["data"]["tenant_id"] == "dev-tenant"

    login = await client.post(
        LOGIN_PATH, json={"username": username, "password": password}
    )
    assert login.status_code == 200
    assert login.json()["data"]["access_token"]


async def test_register_duplicate_username(
    client: AsyncClient, register_user
) -> None:
    """同名注册返回 409。"""
    username, _, _ = await register_user()
    resp = await client.post(
        REGISTER_PATH,
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Passw0rd!2026",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 409


async def test_login_wrong_password(client: AsyncClient, register_user) -> None:
    """密码错误返回 401，且不泄露用户名是否存在。"""
    username, _, _ = await register_user()
    resp = await client.post(
        LOGIN_PATH, json={"username": username, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    """无 token 访问受保护接口返回 401。"""
    resp = await client.get(ME_PATH)
    assert resp.status_code == 401
    assert resp.json()["code"] == 401


async def test_me_rejects_invalid_token(client: AsyncClient) -> None:
    """格式错误的 Bearer 头返回 401。"""
    resp = await client.get(ME_PATH, headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


async def test_refresh_returns_new_token_pair(
    client: AsyncClient, register_user
) -> None:
    """refresh token 可换一对新 token（refresh 带 jti，必然不同）。"""
    _, _, data = await register_user()
    resp = await client.post(
        REFRESH_PATH, json={"refresh_token": data["refresh_token"]}
    )
    assert resp.status_code == 200
    refreshed = resp.json()["data"]
    assert refreshed["access_token"]
    assert refreshed["refresh_token"] != data["refresh_token"]

    me = await client.get(
        ME_PATH, headers={"Authorization": f"Bearer {refreshed['access_token']}"}
    )
    assert me.status_code == 200


async def test_refresh_rejects_access_token(
    client: AsyncClient, register_user
) -> None:
    """access token 不能当 refresh token 用。"""
    _, _, data = await register_user()
    resp = await client.post(
        REFRESH_PATH, json={"refresh_token": data["access_token"]}
    )
    assert resp.status_code == 401
