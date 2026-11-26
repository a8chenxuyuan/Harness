"""Harness Python SDK（W4-API-02）。

面向外部开发者的"开箱可用"客户端，封装 REST API 的统一信封
（{code, message, data}）与 ``hk_`` API Key 鉴权，只依赖 httpx。

用法::

    from harness.sdk import HarnessClient

    async with HarnessClient(base_url="http://localhost:8010/api/v1",
                             api_key="hk_xxx") as client:
        me = await client.whoami()
        skills = await client.skills.list()
"""

from harness.sdk.client import ApiError, HarnessClient

__all__ = ["ApiError", "HarnessClient"]
