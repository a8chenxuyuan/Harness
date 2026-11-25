"""API 请求/响应 DTO（对应 Java Spring 的 dto/request + dto/response）。

原则：
    - Controller 入参用 ``Request`` 结尾的模型
    - Controller 出参用 ``Response`` 结尾的模型
    - 所有字段都带明确 description（FastAPI 自动进 OpenAPI 文档）
"""

from .common import ApiResponse, ApiErrorResponse
