"""API 出参（VO）层。

按业务域一文件，文件名统一 ``<域>_vo.py``：
    - ``envelope_vo.py``  统一响应封装（跨域）
    - ``auth_vo.py``      登录 / 当前用户
    - ``agent_vo.py``     Agent 运行结果
    - ``plan_vo.py``      Plan 摘要与列表
    - ``session_vo.py``   会话详情与列表
    - ``steer_vo.py``     Steering 结果

约定：Controller 出参一律用本层模型，禁止直接返回实体。
"""

from .envelope_vo import ApiErrorResponse, ApiResponse

__all__ = ["ApiResponse", "ApiErrorResponse"]
