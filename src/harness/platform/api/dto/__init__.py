"""API 入参（DTO）层。

按业务域一文件，文件名统一 ``<域>_dto.py``，只放 Controller 请求体模型：
    - ``auth_dto.py``     登录 / 刷新 / 注册
    - ``agent_dto.py``    Agent 运行
    - ``plan_dto.py``     Plan 创建
    - ``session_dto.py``  会话创建
    - ``steer_dto.py``    Steering 操作

约定：Controller 入参一律用本层模型，禁止接收实体或 VO。
"""
