"""基于类型注解的工具反射与 @tool 装饰器。

通过 ``@tool`` 装饰一个普通函数（async / sync 均可），即可得到一个
完整的 :class:`ReflectiveTool` 实例：name、description、parameters
都会被自动推断。

支持的类型 → JSON Schema 映射：
    * ``str`` → string
    * ``int`` → integer
    * ``float`` → number
    * ``bool`` → boolean
    * ``list`` / ``List[T]`` → array（带 items）
    * ``dict`` / ``Dict[K,V]`` → object（带 additionalProperties）
    * ``Optional[T]`` → T，但不出现在 required 列表
    * ``Literal[a, b, c]`` → enum

不支持的类型（Callable、TypeVar 等）统一 fallback 为 object 并打 Warning。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import warnings
from typing import Any, Callable, Literal, get_args, get_origin, get_type_hints

from .base import BaseTool, ToolResult

log = logging.getLogger(__name__)

# 允许的可选 Literal 值类型：JSON Schema enum 只接受这些基础类型
_ENUM_VALUE_TYPES = (str, int, float, bool, type(None))


# ---------------------------------------------------------------------------
# 类型 → JSON Schema 原子映射
# ---------------------------------------------------------------------------

def _builtin_schema(tp: type) -> dict[str, Any] | None:
    """处理非 Generic 的内建基础类型。返回 None 表示未命中。"""
    mapping: dict[type, dict[str, Any]] = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        tuple: {"type": "array"},
        set: {"type": "array"},
        frozenset: {"type": "array"},
        dict: {"type": "object"},
    }
    return mapping.get(tp)


def _literal_schema(tp: Any) -> dict[str, Any] | None:
    """解析 Literal[xxx] → enum schema。值类型必须是 JSON 基础类型。"""
    args = get_args(tp)
    if not args:
        return None
    values: list[Any] = []
    for a in args:
        if not isinstance(a, _ENUM_VALUE_TYPES):
            warnings.warn(
                f"@tool: Literal 值 {a!r} 不是 JSON 可序列化基础类型，已被忽略",
                stacklevel=3,
            )
            continue
        values.append(a)
    if not values:
        return None
    # 推断 base type
    if all(isinstance(v, bool) for v in values):
        base: dict[str, Any] = {"type": "boolean"}
    elif all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        base = {"type": "integer"}
    elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        base = {"type": "number"}
    elif all(isinstance(v, str) for v in values):
        base = {"type": "string"}
    else:
        base = {}
    base["enum"] = values
    return base


def _optional_inner(tp: Any) -> Any | None:
    """若 tp 为 ``Optional[X]`` / ``X | None``，返回 X；否则 None。"""
    # Python 3.10+ X | None 会被 get_origin 识别为 types.UnionType
    origin = get_origin(tp)
    if origin is None:
        return None
    args = get_args(tp)
    if len(args) != 2 or type(None) not in args:
        return None
    inner = next(a for a in args if a is not type(None))
    return inner


def _type_to_schema(tp: Any) -> dict[str, Any]:
    """把一个 Python 类型注解递归转换成 JSON Schema 片段。"""
    # 1) None / NoneType
    if tp is type(None):
        return {"type": "null"}

    # 2) Literal[...]
    origin = get_origin(tp)
    if origin is Literal:
        result = _literal_schema(tp)
        if result is not None:
            return result
        warnings.warn(f"@tool: 无法解析的 Literal {tp}，fallback object", stacklevel=3)
        return {"type": "object"}

    # 3) Optional[X] / X | None → 用 inner 的 schema 即可（required 在外层处理）
    inner = _optional_inner(tp)
    if inner is not None:
        return _type_to_schema(inner)

    # 4) Generic list / dict 等，先处理 inner items
    if origin is list or origin is tuple or origin is set or origin is frozenset:
        schema: dict[str, Any] = {"type": "array"}
        args = get_args(tp)
        if args:
            schema["items"] = _type_to_schema(args[0])
        return schema
    if origin is dict:
        schema = {"type": "object"}
        args = get_args(tp)
        if len(args) == 2:
            # 忽略 key 类型（JSON key 恒为 string），保留 value schema
            schema["additionalProperties"] = _type_to_schema(args[1])
        return schema

    # 5) 内建基础类型
    if isinstance(tp, type):
        schema = _builtin_schema(tp)
        if schema is not None:
            return schema

    # 6) 无法识别 → fallback object
    warnings.warn(f"@tool: 无法解析的类型 {tp!r}，fallback object", stacklevel=3)
    return {"type": "object"}


# ---------------------------------------------------------------------------
# 反射主函数
# ---------------------------------------------------------------------------

def _reflect_from_function(fn: Callable[..., Any]) -> tuple[str, str, dict[str, Any], list[str]]:
    """从函数反射生成 (name, description, parameters_schema, required_list)。"""
    name = fn.__name__

    # description 取 docstring 第一句
    doc = inspect.getdoc(fn) or ""
    description = doc.strip().split("\n", 1)[0].strip()
    if not description:
        description = name

    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # pragma: no cover - 极难触发
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        # 跳过 *args / **kwargs
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue

        tp = hints.get(param_name, Any)
        schema = _type_to_schema(tp)

        if param.default is not inspect.Parameter.empty:
            schema["default"] = param.default
        else:
            # 无默认值才进入 required；但 Optional 参数即使无默认值也不应强制
            inner = _optional_inner(tp)
            if inner is None:
                required.append(param_name)

        properties[param_name] = schema

    parameters = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required

    return name, description, parameters, required


# ---------------------------------------------------------------------------
# ReflectiveTool
# ---------------------------------------------------------------------------

class ReflectiveTool(BaseTool):
    """由 @tool 装饰器从普通函数反射得到的工具类。

    Attributes:
        _fn: 原始函数（async 或 sync）。
        _required: 原始必需参数列表（仅用于 execute 调用时做兜底）。
    """

    def __init__(self, fn: Callable[..., Any], readonly: bool = True) -> None:
        name, description, parameters, required = _reflect_from_function(fn)
        self._fn = fn
        self._required = required
        self.name = name
        self.description = description
        self.parameters = parameters
        self.readonly = readonly

    async def execute(self, **args: Any) -> ToolResult:
        """调用原始函数，自动处理 sync/async 差异并计时。"""
        t0 = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(self._fn):
                value = await self._fn(**args)
            else:
                value = await asyncio.to_thread(self._fn, **args)
        except Exception as exc:  # noqa: BLE001 - 工具异常统一转 ToolResult.error
            ms = (time.perf_counter() - t0) * 1000.0
            return ToolResult(
                ok=False,
                output="",
                error=f"{type(exc).__name__}: {exc}",
                execution_time_ms=ms,
            )

        ms = (time.perf_counter() - t0) * 1000.0
        # 统一把返回值转成字符串
        output = value if isinstance(value, str) else repr(value)
        return ToolResult(ok=True, output=output, execution_time_ms=ms)


# ---------------------------------------------------------------------------
# @tool 装饰器本身
# ---------------------------------------------------------------------------

def tool(
    fn: Callable[..., Any] | None = None,
    *,
    readonly: bool = True,
) -> ReflectiveTool | Callable[[Callable[..., Any]], ReflectiveTool]:
    """把一个普通函数包装成 :class:`ReflectiveTool`。

    用法：
        >>> @tool
        ... async def read_file(path: str, limit: int = 100) -> str:
        ...     '''Read a file.'''
        ...     ...
        >>> read_file.name
        'read_file'
        >>> read_file.parameters["required"]
        ['path']

    也支持带 keyword 的形式：
        >>> @tool(readonly=False)
        ... def write_file(...): ...

    Args:
        fn: 被装饰的函数；None 表示这是 keyword-only 用法。
        readonly: True 表示只读工具可并行，False 表示写操作需串行。

    Returns:
        ReflectiveTool 实例，或用于二次装饰的 wrapper。
    """

    def _wrap(target: Callable[..., Any]) -> ReflectiveTool:
        return ReflectiveTool(target, readonly=readonly)

    if fn is None:
        return _wrap  # keyword-only: @tool(readonly=False)
    return _wrap(fn)  # 位置参数: @tool
