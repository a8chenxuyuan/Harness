"""消息构造快捷函数。

唯一职责：把「写一大段结构」变成「调一个函数」。
不做截断、不做重试、不做压缩——那些属于工具预算与会话层。
"""

from __future__ import annotations

from collections.abc import Sequence

from .content_block import (
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from .msg import Msg
from .role import Role


def system_message(text: str) -> Msg:
    """构造系统消息。

    Args:
        text: 系统提示正文。会话开始后不应再改动，否则前缀失效。

    Returns:
        role 为 system 的消息。
    """
    return Msg(role=Role.SYSTEM, content=[TextBlock(text=text)])


def user_message(text: str) -> Msg:
    """构造用户文本消息。

    Args:
        text: 用户输入。

    Returns:
        role 为 user 的消息。
    """
    return Msg(role=Role.USER, content=[TextBlock(text=text)])


def assistant_message(
    text: str | None = None,
    tool_uses: Sequence[ToolUseBlock] | None = None,
    thinking: ThinkingBlock | None = None,
) -> Msg:
    """构造助手消息，可同时含思考、文本与工具调用。

    Args:
        text: 文本内容，可为空。
        tool_uses: 本轮的工具调用块，可为空。
        thinking: 思考块，可为空。

    Returns:
        role 为 assistant 的消息。

    Raises:
        ValueError: 三种内容都没有。
    """
    blocks: list[TextBlock | ToolUseBlock | ThinkingBlock] = []
    if thinking is not None:
        blocks.append(thinking)
    if text:
        blocks.append(TextBlock(text=text))
    if tool_uses:
        blocks.extend(tool_uses)
    if not blocks:
        raise ValueError("助手消息至少需要 text、tool_uses、thinking 之一")
    return Msg(role=Role.ASSISTANT, content=blocks)


def tool_result_message(
    tool_use_id: str,
    tool_name: str,
    output: str,
    is_error: bool = False,
) -> Msg:
    """构造工具结果消息。

    Args:
        tool_use_id: 对应哪一次工具调用。
        tool_name: 工具名，写入 name 字段。
        output: 工具输出文本。
        is_error: 工具是否失败。

    Returns:
        role 为 tool 的消息。
    """
    return Msg(
        role=Role.TOOL,
        name=tool_name,
        content=[
            ToolResultBlock(tool_use_id=tool_use_id, content=output, is_error=is_error)
        ],
    )


def image_message(url: str | None = None, data: str | None = None, media_type: str = "image/png") -> Msg:
    """构造带图片的用户消息。

    Args:
        url: 图片地址，与 data 二选一。
        data: base64 图片内容，与 url 二选一。
        media_type: MIME 类型。

    Returns:
        role 为 user 的消息。
    """
    return Msg(
        role=Role.USER,
        content=[ImageBlock(media_type=media_type, url=url, data=data)],
    )
