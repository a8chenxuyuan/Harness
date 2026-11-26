"""SDK 核心客户端：请求收发 + 信封解包 + 资源分组挂载（W4-API-02）。

唯一职责：把 HTTP 细节（鉴权头、统一信封、错误转换）收拢到一处，
资源方法见 :mod:`harness.sdk.resources`。不做任何业务编排。
"""

from __future__ import annotations

from typing import Any

import httpx

API_KEY_PREFIX = "hk_"


class ApiError(Exception):
    """SDK 统一业务异常。

    Attributes:
        status_code: HTTP 状态码（401/404/403/429/500 等）。
        code: 业务错误码（来自响应体的 code 字段）。
        message: 人类可读的错误描述。
        detail: 可选的详细信息。
    """

    def __init__(
        self,
        status_code: int,
        code: int,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(f"[{status_code}] {message}" if detail is None else f"[{status_code}] {message} ({detail})")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


class HarnessClient:
    """Harness 平台异步客户端（asyncio 风格，与平台全异步栈一致）。

    Args:
        base_url: API 根地址（含 ``/api/v1`` 前缀，如 ``http://localhost:8010/api/v1``）。
        api_key: 机器调用凭据（``hk_`` 开头），与 token 二选一。
        token: 用户 JWT access_token（浏览器/脚本已登录场景），与 api_key 二选一。
        timeout: 请求超时秒数，默认 30。
        transport: 可注入的 httpx Transport（测试用 ASGITransport 直连 ASGI 应用）。

    Raises:
        ValueError: api_key 与 token 都未提供时。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if api_key:
            credential = api_key
        elif token:
            credential = token
        else:
            raise ValueError("需要提供 api_key（hk_ 前缀）或 token 之一")

        headers = {"Authorization": f"Bearer {credential}"}
        client_kwargs: dict[str, Any] = {
            "base_url": base_url.rstrip("/"),
            "headers": headers,
            "timeout": timeout,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**client_kwargs)

        # 资源分组：一个业务域一个 Api 对象，方法见 resources.py
        from harness.sdk.resources import (
            ApiKeysApi,
            MemoriesApi,
            McpApi,
            SessionsApi,
            SkillsApi,
            ToolsApi,
        )

        self.sessions = SessionsApi(self)
        self.skills = SkillsApi(self)
        self.memories = MemoriesApi(self)
        self.tools = ToolsApi(self)
        self.mcp = McpApi(self)
        self.api_keys = ApiKeysApi(self)

    async def whoami(self) -> dict:
        """查询当前调用者身份（GET /auth/me）。

        Returns:
            UserInfo 字典（user_id / tenant_id / role；机器调用 role=machine）。
        """
        return await self._request("GET", "/auth/me")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """发请求并解包统一信封。

        Returns:
            成功响应的 data 字段（失败直接抛 ApiError，不返回 None 混淆调用方）。

        Raises:
            ApiError: HTTP 非 2xx，或信封 code != 0。
        """
        response = await self._client.request(
            method, path, params=params, json=json_body
        )
        if response.status_code >= 400:
            payload = self._safe_json(response)
            raise ApiError(
                status_code=response.status_code,
                code=int(payload.get("code", response.status_code)),
                message=str(payload.get("message", response.reason_phrase)),
                detail=payload.get("detail"),
            )
        payload = self._safe_json(response)
        if payload.get("code", 0) != 0:
            raise ApiError(
                status_code=response.status_code,
                code=int(payload["code"]),
                message=str(payload.get("message", "unknown")),
            )
        return payload.get("data")

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        """容错解析响应体为 dict（网关层可能返回非 JSON 文本）。"""
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    async def close(self) -> None:
        """释放底层连接池（async with 退出时自动调用）。"""
        await self._client.aclose()

    async def __aenter__(self) -> HarnessClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()


__all__ = ["ApiError", "HarnessClient"]
