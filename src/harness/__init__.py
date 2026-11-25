"""Harness：Prompt 缓存优先的 Python Agent 运行时。

模块化分层（对标 Maven 多模块结构）：

    harness.app             启动入口（create_app → FastAPI 实例）

    harness.common          横切通用件（≈ tdlp-common）
        .config .message .event .extension .observability

    harness.core            运行时内核（≈ tdlp-framework）
        .loop .model .tool .context .session .memory
        .compaction .permission .sandbox

    harness.agents          Agent 抽象与单 Agent 执行（Agent ABC / ReActAgent）
    harness.orchestration   多 Agent 编排（Coordinator / Worker / Plan / Executor）

    harness.integrations    外部生态接入
        .gateway .mcp .skill .hitl

    harness.platform        上线商用层（≈ tdlp-system）
        .api .auth .db .models .repository .service

启动::

    from harness import create_app
    app = create_app()
"""

__version__ = "0.1.0"


def create_app():
    """统一的应用工厂（等价于 ``from harness.app import create_app``）。"""
    from harness.app import create_app as _create_app
    return _create_app()


__all__ = ["__version__", "create_app"]
