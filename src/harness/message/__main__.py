"""消息层自检：验证「同一内容永远产出相同字节」。

运行方式：
    python -m harness.message

输出 PASS / FAIL，进程退出码即为结果。这里不做单元测试框架，
只做一次可人眼核对的现场比对。
"""

from __future__ import annotations

import sys

from .content_block import ImageBlock, ThinkingBlock, ToolUseBlock
from .helpers import (
    assistant_message,
    image_message,
    system_message,
    tool_result_message,
    user_message,
)
from .msg import Msg


def _check(name: str, passed: bool, detail: str = "") -> bool:
    """打印一条检查结果。

    Args:
        name: 检查项名称。
        passed: 是否通过。
        detail: 失败时附加说明。

    Returns:
        原样返回 passed，便于累加。
    """
    prefix = "PASS" if passed else "FAIL"
    suffix = f"  {detail}" if detail and not passed else ""
    print(f"{prefix}  {name}{suffix}")
    return passed


def main() -> int:
    """执行六项比对，返回退出码。"""
    passed: list[bool] = []

    user = user_message("帮我查 parse_config 在哪被调用")
    first = user.canonical_bytes()
    second = user.canonical_bytes()
    passed.append(_check("同一对象两次序列化字节一致", first == second))

    reordered = Msg(
        role=user.role,
        content=list(user.content),
        metadata={"z": 1, "a": 2},
    )
    other_order = Msg(
        role=user.role,
        content=list(user.content),
        metadata={"a": 2, "z": 1},
    )
    passed.append(
        _check(
            "metadata 键插入顺序不影响字节",
            reordered.canonical_bytes() == other_order.canonical_bytes(),
        )
    )

    call_a = ToolUseBlock(id="call_001", name="grep", input={"pattern": "x", "path": "src"})
    call_b = ToolUseBlock(id="call_001", name="grep", input={"path": "src", "pattern": "x"})
    passed.append(
        _check(
            "工具参数键插入顺序不影响字节",
            assistant_message("查一下", [call_a]).canonical_bytes()
            == assistant_message("查一下", [call_b]).canonical_bytes(),
        )
    )

    round_trip = Msg.from_dict(user.to_dict())
    passed.append(_check("字典往返后字节一致", round_trip.canonical_bytes() == first))

    plain = user_message("hi")
    passed.append(
        _check("空字段整体省略而非输出 null", '"name"' not in plain.to_dict(), str(plain.to_dict()))
    )

    chinese = plain.canonical_bytes()
    passed.append(
        _check(
            "中文按 UTF-8 原样保留",
            b"\\u" not in chinese and "hi".encode() in chinese,
        )
    )

    samples = [
        system_message("你是企业代码助手。"),
        user_message("这个函数在哪被调用？"),
        assistant_message(None, [call_a], ThinkingBlock(thinking="先定位符号")),
        tool_result_message("call_001", "grep", "utils.py:12", is_error=False),
        image_message(url="https://example.com/a.png"),
    ]
    joined = b"\n".join(item.canonical_bytes() for item in samples)
    passed.append(_check("五种内容块均可序列化", len(joined) > 0))

    print()
    print("标准样例（用户消息）：")
    print(first.decode("utf-8"))
    print()
    print(f"结果：{sum(passed)}/{len(passed)} 项通过")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
