"""Gateway 插件 SDK（Phase 12 - plugin_sdk）。

提供最小化的动态插件机制：
  - load_plugin(plugin_path) —— importlib 加载模块
  - register_plugin(gateway, plugin) —— 调 plugin.register(gateway)
  - PluginManager —— 管理已加载插件列表

每个插件模块只需要有一个顶层函数 ``register(gateway)``，
可以往 gateway.router 挂新 adapter、挂新 skill、或加新 rule。
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class PluginError(RuntimeError):
    """插件加载/注册失败。"""


@dataclass
class PluginMeta:
    """已加载插件的元信息。

    Attributes:
        name: 模块名（文件名去 .py）。
        path: 文件路径。
        module: 已 import 的模块对象。
    """

    name: str
    path: str
    module: Any = None  # noqa: ANN401 - module 类型不确定


def load_plugin(plugin_path: str | Path) -> PluginMeta:
    """动态加载一个 Python 插件文件。

    Args:
        plugin_path: .py 文件路径。

    Returns:
        PluginMeta。

    Raises:
        PluginError: 文件不存在或 import 失败。
    """
    path = Path(plugin_path)
    if not path.exists():
        raise PluginError(f"plugin 不存在: {path}")

    name = path.stem
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise PluginError(f"无法构造 spec: {path}")

    module = importlib.util.module_from_spec(spec)
    # 注入到 sys.modules，避免插件内部相对 import 失败
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(name, None)
        raise PluginError(f"plugin import 失败 {path}: {exc}") from exc

    return PluginMeta(name=name, path=str(path), module=module)


def register_plugin(gateway: Any, plugin: PluginMeta | Any) -> None:
    """把已加载插件注册到 gateway。

    要求插件模块有顶层 ``register(gateway)`` 函数。

    Args:
        gateway: GatewayServer 或 GatewayRouter 实例——插件自己决定注册什么。
        plugin: PluginMeta 或已加载的模块对象。

    Raises:
        PluginError: register 函数缺失或调用抛异常。
    """
    module = plugin.module if isinstance(plugin, PluginMeta) else plugin
    name = plugin.name if isinstance(plugin, PluginMeta) else getattr(module, "__name__", "<unknown>")

    if not hasattr(module, "register"):
        raise PluginError(f"plugin {name} 缺少 register(gateway) 函数")
    if not callable(module.register):
        raise PluginError(f"plugin {name}.register 不是 callable")

    try:
        result = module.register(gateway)
    except Exception as exc:  # noqa: BLE001
        raise PluginError(f"plugin {name}.register() 调用抛异常: {exc}") from exc

    log.info("plugin %s registered, register() returned %r", name, result)


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class PluginManager:
    """管理一批已加载插件的集合。

    典型用法::

        pm = PluginManager()
        pm.load("/path/to/my_plugin.py", gateway)
        pm.list_plugins()
        pm.reload_plugin("my_plugin", gateway)
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginMeta] = {}
        self._gateway: Any = None  # noqa: ANN401

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[PluginMeta]:
        """列出所有已加载插件。"""
        return list(self._plugins.values())

    def has_plugin(self, name: str) -> bool:
        """是否已加载某个 name。"""
        return name in self._plugins

    def load(self, plugin_path: str | Path, gateway: Any | None = None) -> PluginMeta:
        """加载并注册一个插件。

        Args:
            plugin_path: .py 文件路径。
            gateway: 可选的 gateway；不传则使用第一次 load 时保存的 gateway。

        Returns:
            PluginMeta。
        """
        gw = gateway or self._gateway
        if gw is not None:
            self._gateway = gw

        meta = load_plugin(plugin_path)
        register_plugin(gw, meta)
        self._plugins[meta.name] = meta
        return meta

    def reload_plugin(self, name: str, gateway: Any | None = None) -> PluginMeta:
        """强制重新加载一个已存在的插件（从磁盘重新 import）。

        Args:
            name: 已加载插件的模块名。
            gateway: 可选 gateway（不传则用保存的）。

        Returns:
            新的 PluginMeta。

        Raises:
            PluginError: name 不存在。
        """
        gw = gateway or self._gateway
        old = self._plugins.get(name)
        if old is None:
            raise PluginError(f"plugin {name} 未加载")

        # 从 sys.modules 移除旧模块
        sys.modules.pop(name, None)

        new_meta = load_plugin(old.path)
        register_plugin(gw, new_meta)
        self._plugins[name] = new_meta
        log.info("plugin %s reloaded", name)
        return new_meta

    def remove_plugin(self, name: str) -> PluginMeta | None:
        """移除一个已加载插件（从 sys.modules 和 manager 同时移除）。

        Args:
            name: 模块名。

        Returns:
            被移除的 PluginMeta；没找到返回 None。
        """
        meta = self._plugins.pop(name, None)
        if meta is not None:
            sys.modules.pop(name, None)
            log.info("plugin %s removed", name)
        return meta
