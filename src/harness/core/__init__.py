"""Harness 运行时内核（≈ Java 分层的 framework 模块）。

子模块：
    - loop        Agent 运行时内核（run_loop / state / streaming / react_graph）
    - model       LLM 抽象（Model ABC / OpenAICompat / Anthropic）
    - tool        工具抽象（Tool ABC / Registry / Budget / Executor）
    - context     上下文组装（ContextAssembler / TokenBudget / cache_policy）
    - session     会话存储（SessionStore / Checkpoint）
    - memory      记忆（InMemory / LongTerm / SessionView）
    - compaction  上下文压缩策略
    - permission  权限引擎（PermissionEngine / Mode / Rule）
    - sandbox     执行沙箱（Process / Docker）

本包只做命名空间容器，不聚合 re-export —— 按需从子模块精确 import。
"""
