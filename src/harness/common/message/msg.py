"""消息容器：对话里的一条完整消息。

唯一职责：把若干内容块按顺序装进一条消息，并保证同一份内容
每次导出完全相同的字节。
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .canonical import canonical_bytes, sorted_deep
from .content_block import ContentBlock
from .role import Role

_BLOCK_ADAPTER: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)

# 字段导出顺序固定写死在这里。顺序一变，前缀字节就变，缓存立刻失效。
_FIELD_ORDER = ("id", "role", "name", "content", "metadata")


class Msg(BaseModel):
    """一条消息。

    Attributes:
        id: 消息编号。空串表示尚未由会话层分配。
        role: 发送方角色。
        name: 工具名或发言人名，缺省不出现。
        content: 至少一个内容块，顺序即语义。
        metadata: 渠道来源等附加信息，不参与模型请求时可以为空。
    """

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    role: Role
    name: str | None = None
    content: list[ContentBlock] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """导出可序列化字典，字段顺序固定、空值省略、嵌套字典排序。

        Returns:
            键顺序为 id / role / name(可选) / content / metadata 的字典。
        """
        ordered: dict[str, Any] = {}
        for field_name in _FIELD_ORDER:
            if field_name == "content":
                ordered["content"] = [block.to_dict() for block in self.content]
            elif field_name == "role":
                ordered["role"] = self.role.value
            elif field_name == "metadata":
                ordered["metadata"] = sorted_deep(self.metadata)
            elif field_name == "name":
                if self.name is not None:
                    ordered["name"] = self.name
            else:
                ordered[field_name] = getattr(self, field_name)
        return ordered

    def canonical_bytes(self) -> bytes:
        """返回规范 UTF-8 字节。

        Returns:
            同一内容无论构造几次、键插入顺序如何都完全一致的字节串。
        """
        return canonical_bytes(self.to_dict())

    def text(self) -> str:
        """拼接所有文本块，便于日志与断言使用。

        Returns:
            文本块内容的直接拼接结果；没有文本块时返回空串。
        """
        return "".join(
            block.text for block in self.content if getattr(block, "type", "") == "text"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Msg:
        """从字典还原消息，用于会话持久化后的回放。

        Args:
            payload: 由 to_dict() 产出的字典。

        Returns:
            校验通过的消息对象。

        Raises:
            KeyError: 缺少 role 或 content。
            pydantic.ValidationError: 内容块类型非法。
        """
        raw_blocks = payload["content"]
        blocks = [_BLOCK_ADAPTER.validate_python(item) for item in raw_blocks]
        return cls(
            id=str(payload.get("id", "")),
            role=payload["role"],
            name=payload.get("name"),
            content=blocks,
            metadata=dict(payload.get("metadata") or {}),
        )
