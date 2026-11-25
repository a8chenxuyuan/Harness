"""Harness Service 层（对应 Java Spring 的 service/）。

Service 层职责：
    - 桥接 HTTP Controller 和底层引擎（orchestration / tool / agent）
    - 编排多个 Repository / 底层组件完成一个业务用例
    - 不放任何 FastAPI 路由装饰器
    - 不直接操作 Request / Response 对象（DTO 在 Controller 层处理）

调用链：Controller → Service → Repository / 引擎层
"""
