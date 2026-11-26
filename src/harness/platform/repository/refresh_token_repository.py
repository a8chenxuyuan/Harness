"""RefreshTokenRepository — refresh token 记录读写（W3-SEC-01）。"""

from __future__ import annotations


class RefreshTokenRepository:
    """负责签发落库、轮换与吊销。"""

    def __init__(self, session) -> None:
        self.session = session

    async def add(self, record):
        self.session.add(record)
        await self.session.commit()
        return record

    async def get(self, jti: str):
        from harness.platform.entity.refresh_token import RefreshToken

        return await self.session.get(RefreshToken, jti)

    async def rotate(self, old, new_record):
        """同一事务内吊销旧记录并写入新记录。"""
        from datetime import datetime, timezone

        old.revoked_at = datetime.now(timezone.utc)
        old.replaced_by = new_record.jti
        self.session.add(old)
        self.session.add(new_record)
        await self.session.commit()
        return new_record

    async def revoke(self, jti: str) -> bool:
        """吊销单个 jti（幂等）。"""
        from datetime import datetime, timezone

        record = await self.get(jti)
        if record is None:
            return False
        if record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            self.session.add(record)
            await self.session.commit()
        return True

    async def revoke_all_for_user(self, user_id: str) -> int:
        """吊销某用户全部未吊销 refresh token（重放处置）。"""
        from datetime import datetime, timezone
        from sqlalchemy import update

        from harness.platform.entity.refresh_token import RefreshToken

        result = await self.session.exec(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await self.session.commit()
        return int(result.rowcount or 0)
