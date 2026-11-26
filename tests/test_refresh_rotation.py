"""refresh token 轮换与吊销测试（W3-SEC-01）。"""

from __future__ import annotations

REFRESH_PATH = "/api/v1/auth/refresh"
LOGOUT_PATH = "/api/v1/auth/logout"


async def test_refresh_rotates_and_replay_revokes_all(
    client, register_user, db_session
) -> None:
    """刷新轮换旧 token；重放旧 token 会吊销该用户全部 refresh token。"""
    from harness.platform.auth.jwt import decode_refresh_token
    from harness.platform.repository.refresh_token_repository import (
        RefreshTokenRepository,
    )

    _, _, data = await register_user()
    old_token = data["refresh_token"]
    old_jti = decode_refresh_token(old_token)["jti"]

    repo = RefreshTokenRepository(db_session)
    stored = await repo.get(old_jti)
    assert stored is not None
    assert stored.revoked_at is None

    rotated = await client.post(REFRESH_PATH, json={"refresh_token": old_token})
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["data"]["refresh_token"]

    db_session.expire_all()
    old_record = await repo.get(old_jti)
    assert old_record.revoked_at is not None
    assert old_record.replaced_by is not None

    # 重放旧 token：401，并吊销全部（包括刚签发的新 token）
    replay = await client.post(REFRESH_PATH, json={"refresh_token": old_token})
    assert replay.status_code == 401

    after_replay = await client.post(
        REFRESH_PATH, json={"refresh_token": new_token}
    )
    assert after_replay.status_code == 401


async def test_logout_revokes_refresh_token(client, register_user) -> None:
    """登出携带 refresh token 后，该 token 不能再刷新。"""
    _, _, data = await register_user()

    logout = await client.post(
        LOGOUT_PATH,
        json={"refresh_token": data["refresh_token"]},
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert logout.status_code == 200, logout.text
    assert logout.json()["data"]["refresh_revoked"] is True

    refreshed = await client.post(
        REFRESH_PATH, json={"refresh_token": data["refresh_token"]}
    )
    assert refreshed.status_code == 401


async def test_logout_without_body_still_works(client, register_user) -> None:
    """不传 body 的旧客户端仍可登出。"""
    _, _, data = await register_user()

    resp = await client.post(
        LOGOUT_PATH,
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["refresh_revoked"] is False
