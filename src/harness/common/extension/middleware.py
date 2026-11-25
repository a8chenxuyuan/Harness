"""三种 Middleware 模式 + MiddlewareChain 串联器（Phase 16）。

设计思路：
  - Onion        —— 洋葱模型：pre → 原 handler → post；pre 可短路，post 可改 response
  - Transformer  —— 只处理输入/输出，不影响主流程的存在性
  - Notification —— 纯 side effect，不返回任何东西也不改变响应
  - MiddlewareChain —— 把上述三种的任意组合按顺序 wrap 成一个 callable

所有 Middleware 都是 Middleware 的子类（ABC），只需要实现
``async wrap(request, handler) -> response`` 即可。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Sequence

log = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[Any]]


class Middleware(ABC):
    """中间件基类。

    子类必须实现 :meth:`wrap`，接受一个 ``request``（任意输入）和下一个
    ``handler``，返回最终响应。大多数子类不需要直接继承此 ABC，而是使用
    下面三个具体子类：Onion / Transformer / Notification。
    """

    @abstractmethod
    async def wrap(self, request: Any, handler: Handler) -> Any:
        """把自身逻辑插入 ``handler`` 之前/之后。

        Args:
            request: 原始请求对象（或任意输入）。
            handler: 下一个处理函数（可以是原始业务 handler，也可以是
                     MiddlewareChain 产出的组合 callable）。

        Returns:
            传给上游/下游的 response。
        """
        ...


class Onion(Middleware):
    """洋葱模型中间件：pre → 执行原 handler → post。

    ``pre`` 返回非 None 时直接短路，不再往下走；
    ``post`` 拿到原始 response 后可以改写再返回。

    典型用途：鉴权、限流、统一响应封装。
    """

    def __init__(
        self,
        pre: Callable[[Any], Any | None] | None = None,
        post: Callable[[Any, Any], Any] | None = None,
    ) -> None:
        """初始化。

        Args:
            pre: 前置函数，签名 ``pre(request) -> response | None``。返回
                 非 None 则短路；返回 None 继续调用下游 handler。
            post: 后置函数，签名 ``post(request, response) -> new_response``。
                  不提供时原样透传。
        """
        self._pre = pre
        self._post = post

    async def wrap(self, request: Any, handler: Handler) -> Any:
        # 1. pre
        if self._pre is not None:
            pre_result = self._pre(request)
            if pre_result is not None:
                log.debug("Onion.pre 短路: %s", type(self).__name__)
                return pre_result

        # 2. 原 handler
        response = await handler(request)

        # 3. post
        if self._post is not None:
            response = self._post(request, response)

        return response


class Transformer(Middleware):
    """只做输入/输出变形的中间件。

    ``transform_input`` 改 request，``transform_output`` 改 response。
    没有短路或中断能力。
    """

    def __init__(
        self,
        transform_input: Callable[[Any], Any] | None = None,
        transform_output: Callable[[Any], Any] | None = None,
    ) -> None:
        """初始化。

        Args:
            transform_input: 输入变形函数。None 表示不处理输入。
            transform_output: 输出变形函数。None 表示不处理输出。
        """
        self._ti = transform_input
        self._to = transform_output

    async def wrap(self, request: Any, handler: Handler) -> Any:
        req = self._ti(request) if self._ti is not None else request
        response = await handler(req)
        return self._to(response) if self._to is not None else response


class Notification(Middleware):
    """纯 side-effect 中间件。

    ``notify`` 会被同步调用，其返回值被忽略；异常会被吞掉只打 warning，
    绝不能中断主流程。
    """

    def __init__(self, notify: Callable[[Any, Any | None], Any]) -> None:
        """初始化。

        Args:
            notify: 通知函数 ``notify(request, response | None)``。在
                    handler 执行前（response=None）和执行后各调一次，
                    方便做 "before/after" 语义的埋点。
        """
        self._notify = notify

    async def wrap(self, request: Any, handler: Handler) -> Any:
        # before
        try:
            self._notify(request, None)
        except Exception:  # noqa: BLE001
            log.warning("Notification before 抛异常，已吞掉", exc_info=True)

        response = await handler(request)

        # after
        try:
            self._notify(request, response)
        except Exception:  # noqa: BLE001
            log.warning("Notification after 抛异常，已吞掉", exc_info=True)

        return response


class MiddlewareChain(Middleware):
    """把多个 Middleware 按顺序串联成一个 callable。

    ``wrap`` 会构造一个洋葱式调用栈：最外层的 middleware 先进入，
    最里层的 middleware 最先离开，形成 pre 正序、post 逆序。

    支持 ``list`` 形式的便捷构造::

        chain = MiddlewareChain([onion, transformer, notification])
        wrapped = await chain.wrap(handler=my_handler)
    """

    def __init__(self, middlewares: Sequence[Middleware] | None = None) -> None:
        """初始化。

        Args:
            middlewares: 可选的初始列表，也可以后续用 :meth:`add` 追加。
        """
        self._chain: list[Middleware] = list(middlewares) if middlewares else []

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def add(self, middleware: Middleware) -> None:
        """追加一个 middleware 到链尾。

        Args:
            middleware: Middleware 实例。
        """
        self._chain.append(middleware)

    def list(self) -> list[Middleware]:
        """返回链内所有 middleware 的拷贝。"""
        return list(self._chain)

    async def wrap(self, handler: Handler, request: Any = None) -> Any:
        """把链应用到 ``handler`` 上。

        两种调用方式：
        - ``chain.wrap(request, handler)`` —— 一次性执行（基类 ABC 签名）
        - ``await chain.wrap(handler=my_handler)`` —— 返回组合后的 callable 再手动调用
          （推荐，与 FastAPI 等框架的 ``app = chain.wrap(original_app)`` 用法对齐）

        本实现用 keyword 参数区分两种语义：提供 ``request`` 时立即执行，
        否则返回一个包装好的 callable。

        Args:
            handler: 原始业务 handler。
            request: 可选请求；提供时立即执行并返回 response，
                     不提供时返回一个 ``async def inner(req)`` 包装器。

        Returns:
            提供 ``request`` 时返回 handler 的响应；否则返回包装 callable。
        """
        # 反向包：最后一个 middleware 最先被 "包住" handler
        combined = handler
        for mw in reversed(self._chain):
            _inner = combined  # capture current combined
            _mw = mw

            async def _next(req: Any, _cur_handler: Handler = _inner, _cur_mw: Middleware = _mw) -> Any:
                return await _cur_mw.wrap(req, _cur_handler)

            combined = _next  # type: ignore[assignment]

        # 两种调用方式
        if request is not None:
            return await combined(request)

        # 返回包装好的 callable
        return combined  # type: ignore[return-value]
