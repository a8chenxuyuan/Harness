"""Repository 基类 — 通用 CRUD。

⚠️ SQLModel / SQLAlchemy 全部延迟加载，class 定义时不触发 C 扩展。
"""

from __future__ import annotations

from typing import Generic, TypeVar, Type

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """通用 CRUD 基类。

    子类只需指定 ``model``，就自动获得 get_by_id / list / save / delete 等方法。

    Attributes:
        model: SQLModel table 类（子类 override）。
    """

    model: Type[T]

    def __init__(self, session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 通用 CRUD
    # ------------------------------------------------------------------

    async def get(self, id_value: str) -> T | None:
        """按主键查询。"""
        return await self.session.get(self.model, id_value)

    async def list(self, *, offset: int = 0, limit: int = 50) -> list[T]:
        """分页查询。"""
        from sqlmodel import select
        result = await self.session.exec(
            select(self.model).offset(offset).limit(limit)
        )
        return list(result.all())

    async def save(self, entity: T) -> T:
        """新增或更新。"""
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def delete(self, id_value: str) -> bool:
        """按主键删除。"""
        entity = await self.get(id_value)
        if entity is None:
            return False
        await self.session.delete(entity)
        await self.session.commit()
        return True
