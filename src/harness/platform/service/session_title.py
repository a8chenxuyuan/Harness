"""会话标题自动生成 — 从首条用户消息提取简洁标题。

设计取舍：标题在消息写入的副作用路径中生成，必须零额外延迟与成本，
因此不调用模型，只做文本归一化与截断；后续若改为模型摘要，
替换 ``build_title`` 实现即可，调用方无需改动。
"""

from __future__ import annotations

# 标题长度上限（sessions.title 列宽 256，这里按列表可读性收敛）
TITLE_LIMIT = 30

# 视为「尚未命名」的标题前缀 / 占位值
_AUTO_PREFIXES = ("新会话", "未命名会话")
_PLACEHOLDERS = frozenset({"", "会话"})


def build_title(text: str, *, limit: int = TITLE_LIMIT) -> str:
    """把用户输入压缩成一行标题；空输入返回空串。"""
    normalized = " ".join((text or "").split())
    normalized = normalized.lstrip("#>-* ").strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}…"


def needs_auto_title(title: str) -> bool:
    """判断标题是否仍为自动占位（空 / 新会话 / 未命名），需要自动生成。"""
    value = (title or "").strip()
    if value in _PLACEHOLDERS:
        return True
    return value.startswith(_AUTO_PREFIXES)


__all__ = ["TITLE_LIMIT", "build_title", "needs_auto_title"]
