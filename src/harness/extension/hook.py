"""Hook 事件枚举与 JSONL 追踪导出（Phase 16）。

Hook 是 Agent 循环里的生命周期钩子，比 Middleware 更细粒度：
  - PRE_REASONING / POST_REASONING —— 模型思考前后
  - PRE_TOOL / POST_TOOL —— 单个工具调用前后
  - PRE_COMPACTION / POST_COMPACTION —— 上下文压缩前后

JsonlTraceExporter 把每个 event 以 JSON Lines 形式追加到文件，
方便离线调试 / replay。
"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class HookEventType(str, Enum):
    """Agent 循环可插桩的生命周期事件。

    值使用 snake_case 字符串方便写入 JSONL。
    """

    PRE_REASONING = "pre_reasoning"
    """模型调用前。payload 含 messages 和当前 token 预算。"""

    POST_REASONING = "post_reasoning"
    """模型调用后。payload 含 finish_reason、tool_calls、ttft 等。"""

    PRE_TOOL = "pre_tool"
    """单个工具执行前。payload 含 tool_name 和 args。"""

    POST_TOOL = "post_tool"
    """单个工具执行后。payload 含 tool_result（ok/error/output）和耗时。"""

    PRE_COMPACTION = "pre_compaction"
    """上下文压缩触发前。payload 含触发原因和当前 token 数。"""

    POST_COMPACTION = "post_compaction"
    """上下文压缩完成后。payload 含压缩率和新 token 数。"""


class Hook(ABC):
    """生命周期钩子基类。

    子类只需实现 :meth:`on`，接收事件类型和 payload。任何异常都应该
    子类内部吞掉，不允许往主流程抛——Hook 是可丢失的观测面。
    """

    @abstractmethod
    def on(self, event: HookEventType, payload: dict[str, Any]) -> None:
        """处理一次事件。

        Args:
            event: 事件类型。
            payload: 事件载荷（不同事件 payload 结构不同）。
        """
        ...


class JsonlTraceExporter(Hook):
    """把每个 Hook 事件追加到 JSONL 文件。

    适合调试、回放和对接 ELK / Splunk 等日志系统。内部用线程锁保证
    跨协程/线程的写入安全。

    用法::

        exporter = JsonlTraceExporter("/tmp/trace.jsonl")
        # 在 Agent 循环里：hook.on(HookEventType.PRE_REASONING, {...})
    """

    def __init__(
        self,
        path: str | Path,
        *,
        append: bool = True,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """初始化。

        Args:
            path: JSONL 文件路径，父目录不存在时会自动创建。
            append: True 时追加，False 时启动会清空文件。
            extra_fields: 每条记录都会写入的固定字段（如 service_name）。
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._append = append
        self._extra = dict(extra_fields) if extra_fields else {}
        self._lock = threading.Lock()

        # 非 append 模式：清空文件
        if not append:
            self._path.write_text("", encoding="utf-8")

    # ------------------------------------------------------------------
    # Hook 接口
    # ------------------------------------------------------------------

    def on(self, event: HookEventType, payload: dict[str, Any]) -> None:
        """把事件追加一行 JSONL。

        Args:
            event: 事件类型。
            payload: 事件载荷。异常会被吞掉只打 warning。
        """
        try:
            record = {
                "event": event.value,
                "payload": payload,
                **self._extra,
            }
            line = json.dumps(record, ensure_ascii=False, default=str)

            with self._lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:  # noqa: BLE001
            log.warning("JsonlTraceExporter 写入失败", exc_info=True)

    # ------------------------------------------------------------------
    # 附加 API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """底层文件路径。"""
        return self._path

    def read_tail(self, n: int = 100) -> list[dict[str, Any]]:
        """读取末尾 n 条记录（调试用）。

        Args:
            n: 最多返回行数。

        Returns:
            解析后的 JSON 对象列表，顺序与文件内一致（旧 → 新）。
        """
        if not self._path.exists():
            return []

        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()

        tail = lines[-n:]
        result: list[dict[str, Any]] = []
        for line in tail:
            if not line.strip():
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result
