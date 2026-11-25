"""Repository 层 — 数据访问抽象（对应 Java 的 Repository / Mapper）。

原则：
    - 只管 CRUD，不写业务逻辑
    - 所有方法都是 async
    - 基类 BaseRepository 提供通用 CRUD，子类只补自定义查询
"""
