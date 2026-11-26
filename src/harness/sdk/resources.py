"""SDK 资源分组：一个业务域一个 Api 类（W4-API-02）。

每个类只做"参数拼装 + 委托 client._request"，不写业务逻辑。
方法名与 REST 路由一一对应，返回值统一是 dict（信封的 data 字段）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.sdk.client import HarnessClient


class SessionsApi:
    """会话资源：创建 / 列表 / 详情 / 归档（REST /sessions）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def create(self, title: str | None = None, metadata: dict | None = None) -> dict:
        """创建新会话（POST /sessions）。"""
        body: dict[str, Any] = {"title": title, "metadata": metadata or {}}
        return await self._client._request("POST", "/sessions", json_body=body)

    async def list(self, page: int = 1, size: int = 20, status: str | None = None) -> dict:
        """分页列出会话（GET /sessions，status 可选 active/archived/all）。"""
        params: dict[str, Any] = {"page": page, "size": size}
        if status:
            params["status"] = status
        return await self._client._request("GET", "/sessions", params=params)

    async def get(self, session_id: str) -> dict:
        """查会话详情（GET /sessions/{id}，租户隔离）。"""
        return await self._client._request("GET", f"/sessions/{session_id}")

    async def archive(self, session_id: str) -> dict:
        """归档会话（POST /sessions/{id}/archive）。"""
        return await self._client._request("POST", f"/sessions/{session_id}/archive")


class SkillsApi:
    """Skill 资源：注册 / 启停 / 版本 / 触发测试（REST /skills）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def list(self) -> dict:
        """列出全部 Skill（GET /skills，四层优先级排序）。"""
        return await self._client._request("GET", "/skills")

    async def get(self, name: str) -> dict:
        """查单个 Skill 详情（GET /skills/{name}，不存在返回 skill=null）。"""
        return await self._client._request("GET", f"/skills/{name}")

    async def register(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        triggers: list[str] | None = None,
        tools: list[str] | None = None,
        custom_message: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """注册运行时层 Skill（POST /skills，同名覆盖热更新）。

        Returns:
            含 skill 与 replaced（是否覆盖了旧版本）两个字段。
        """
        body: dict[str, Any] = {
            "name": name,
            "description": description,
            "version": version,
            "triggers": triggers or [],
            "tools": tools or [],
            "custom_message": custom_message,
            "metadata": metadata or {},
        }
        return await self._client._request("POST", "/skills", json_body=body)

    async def set_enabled(self, name: str, enabled: bool) -> dict:
        """启用/禁用 Skill（PATCH /skills/{name}，进程内内存态）。"""
        return await self._client._request(
            "PATCH", f"/skills/{name}", json_body={"enabled": enabled}
        )

    async def enable(self, name: str) -> dict:
        """启用 Skill（set_enabled 的语义化别名）。"""
        return await self.set_enabled(name, True)

    async def disable(self, name: str) -> dict:
        """禁用 Skill（set_enabled 的语义化别名）。"""
        return await self.set_enabled(name, False)

    async def versions(self, name: str) -> dict:
        """查历史版本（GET /skills/{name}/versions，仅记录被覆盖的旧版本）。"""
        return await self._client._request("GET", f"/skills/{name}/versions")

    async def delete(self, name: str) -> dict:
        """注销运行时层 Skill（DELETE /skills/{name}，低层 Skill 返回 403）。"""
        return await self._client._request("DELETE", f"/skills/{name}")

    async def trigger_test(self, text: str) -> dict:
        """触发测试（POST /skills/trigger-test，仅匹配不激活）。"""
        return await self._client._request(
            "POST", "/skills/trigger-test", json_body={"text": text}
        )


class MemoriesApi:
    """长期记忆资源：搜索 / 保存 / 删除（REST /memories）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def list(
        self,
        keyword: str = "",
        limit: int = 50,
        offset: int = 0,
        session_id: str | None = None,
    ) -> dict:
        """分页查记忆（GET /memories，keyword LIKE 匹配，total 不受分页限制）。"""
        params: dict[str, Any] = {"keyword": keyword, "limit": limit, "offset": offset}
        if session_id:
            params["session_id"] = session_id
        return await self._client._request("GET", "/memories", params=params)

    async def save(
        self,
        content: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """手动保存一条记忆（POST /memories，保存后立即可被检索）。"""
        body: dict[str, Any] = {
            "content": content,
            "session_id": session_id,
            "tags": tags or [],
            "metadata": metadata or {},
        }
        return await self._client._request("POST", "/memories", json_body=body)

    async def delete(self, item_id: str) -> dict:
        """删除一条记忆（DELETE /memories/{id}，不存在返回 404）。"""
        return await self._client._request("DELETE", f"/memories/{item_id}")


class ToolsApi:
    """工具资源：内置目录 / 全量市场 / 只读调试（REST /tools）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def list(self) -> dict:
        """列出内置工具目录（GET /tools，顺序稳定）。"""
        return await self._client._request("GET", "/tools")

    async def market(self) -> dict:
        """查全量工具市场（GET /tools/market，内置 + MCP，标注来源）。"""
        return await self._client._request("GET", "/tools/market")

    async def debug(self, name: str, arguments: dict | None = None) -> dict:
        """只读调试执行工具（POST /tools/{name}/debug，写类工具 403）。"""
        return await self._client._request(
            "POST", f"/tools/{name}/debug", json_body={"arguments": arguments or {}}
        )


class McpApi:
    """MCP server 资源：注册 / 列表 / 注销（REST /mcp/servers）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def list_servers(self) -> dict:
        """列出已注册 MCP server（GET /mcp/servers）。"""
        return await self._client._request("GET", "/mcp/servers")

    async def register_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict:
        """注册 stdio MCP server（POST /mcp/servers，注册前握手验证）。"""
        body: dict[str, Any] = {
            "name": name,
            "command": command,
            "args": args or [],
            "env": env or {},
        }
        return await self._client._request("POST", "/mcp/servers", json_body=body)

    async def delete_server(self, name: str) -> dict:
        """注销 MCP server 并回收其工具（DELETE /mcp/servers/{name}）。"""
        return await self._client._request("DELETE", f"/mcp/servers/{name}")


class ApiKeysApi:
    """API Key 资源：签发 / 列表 / 吊销（REST /api-keys，W4-API-01）。"""

    def __init__(self, client: HarnessClient) -> None:
        self._client = client

    async def create(self, name: str, expires_in_days: int | None = None) -> dict:
        """签发新 key（POST /api-keys，明文只在本次响应出现一次）。"""
        body: dict[str, Any] = {"name": name, "expires_in_days": expires_in_days}
        return await self._client._request("POST", "/api-keys", json_body=body)

    async def list(self) -> dict:
        """列出全部 key（GET /api-keys，脱敏，不含哈希与明文）。"""
        return await self._client._request("GET", "/api-keys")

    async def revoke(self, key_id: str) -> dict:
        """吊销 key（DELETE /api-keys/{id}，重复吊销幂等）。"""
        return await self._client._request("DELETE", f"/api-keys/{key_id}")


__all__ = [
    "ApiKeysApi",
    "MemoriesApi",
    "McpApi",
    "SessionsApi",
    "SkillsApi",
    "ToolsApi",
]
