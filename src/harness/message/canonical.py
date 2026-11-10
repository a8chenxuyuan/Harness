"""规范序列化：保证同一份数据每次产出完全相同的字节。

为什么需要单独一个模块：
    Prompt 前缀缓存只认「字节完全一致」的前缀。Python 的 dict 保留插入顺序，
    同一份数据如果键的插入顺序不同，json.dumps 出来的字节就不同，缓存必然失效。
    因此所有进入前缀的内容都必须经过这里排序。

这里只做两件事：递归按键名排序、固定分隔符输出。
不负责字段取舍（哪些字段该省略由各模型自己决定）。
"""

from __future__ import annotations

import json
from typing import Any


def sorted_deep(value: Any) -> Any:
    """递归按键名排序字典。

    Args:
        value: 任意可 JSON 化的值。

    Returns:
        字典键按字典序排列的新结构；列表逐项处理；其他类型原样返回。
    """
    if isinstance(value, dict):
        return {key: sorted_deep(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [sorted_deep(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """把任意结构序列化成规范 JSON 字符串。

    Args:
        value: 待序列化的结构，通常已经过排序。

    Returns:
        无空格、键有序、非 ASCII 字符原样保留（不转 \\uXXXX）的 JSON 文本。
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """序列化为 UTF-8 字节串。

    Args:
        value: 待序列化的结构。

    Returns:
        UTF-8 编码的规范 JSON 字节。
    """
    return canonical_json(value).encode("utf-8")
