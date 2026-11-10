"""内容块：一条消息里的一小块内容。

五种块就够了，其余（video / audio / document）在本阶段只保留扩展位，
不定义具体类型——没被用到的类型定义会成为长期维护负担。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import sorted_deep


class BlockBase(BaseModel):
    """所有内容块的公共基类。

    统一禁止未声明字段：多传一个键会导致序列化结果与原意不一致，
    在缓存场景下等于悄悄改写前缀。
    """

    model_config = ConfigDict(extra="forbid")


class TextBlock(BlockBase):
    """纯文本块。"""

    type: Literal["text"] = "text"
    text: str

    def to_dict(self) -> dict[str, Any]:
        """按固定字段顺序导出字典。"""
        return {"type": self.type, "text": self.text}


class ThinkingBlock(BlockBase):
    """思考块。

    signature 是 Anthropic 回放思考内容时必须带上的签名，
    其他供应商为空时整体省略该字段。
    """

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """按固定字段顺序导出字典。"""
        data: dict[str, Any] = {"type": self.type, "thinking": self.thinking}
        if self.signature is not None:
            data["signature"] = self.signature
        return data


class ImageBlock(BlockBase):
    """图片块。data（base64）与 url 二选一。"""

    type: Literal["image"] = "image"
    media_type: str
    data: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> ImageBlock:
        """校验 data 与 url 必须恰好提供一个。

        Raises:
            ValueError: 两者都给或都不给。
        """
        if (self.data is None) == (self.url is None):
            raise ValueError("image 块必须且只能提供 data 或 url 之一")
        return self

    def to_dict(self) -> dict[str, Any]:
        """按固定字段顺序导出字典。"""
        data: dict[str, Any] = {"type": self.type, "media_type": self.media_type}
        if self.data is not None:
            data["data"] = self.data
        if self.url is not None:
            data["url"] = self.url
        return data


class ToolUseBlock(BlockBase):
    """工具调用块，由模型输出。

    input 是模型给的原始参数，进入前缀前必须按键名排序，
    否则同一次调用换个参数顺序就会让缓存失效。
    """

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """按固定字段顺序导出字典，参数键名递归排序。"""
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "input": sorted_deep(self.input),
        }


class ToolResultBlock(BlockBase):
    """工具执行结果块，由运行时回填。"""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        """按固定字段顺序导出字典。"""
        return {
            "type": self.type,
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
        }


ContentBlock = Annotated[
    Union[TextBlock, ThinkingBlock, ImageBlock, ToolUseBlock, ToolResultBlock],
    Field(discriminator="type"),
]
"""内容块判别联合：依据 type 字段决定实例化哪个具体类型。"""
