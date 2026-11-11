# Harness 融合框架 · 实现路线图

> 配套文档：`docs/framework-design.md`（v2.0）
>
> 本路线图按「运行时强且快」组织，不按「功能多」组织。每个 Phase 都有**可度量的运行时验收指标**，不是只写 PASS。

---

## 0. 总体约定

### 0.1 「强且快」的准确定义

不是开发快，是**用起来比 AgentScope 2.0 / OpenClaw / LangGraph 更强、更快**：

- **强**：上表全部能力都在，且能组合使用（不会因为加了 Skill 就破坏缓存，加了 Memory 就变慢）。
- **快**：长会话 token 成本与 TTFT 不随轮次上涨；工具等待可重叠；崩溃恢复不重跑。

### 0.2 三条设计铁律

1. **缓存优先**：系统提示 / 工具定义 / 历史只追加不改写；压缩 = 追加 entry。
2. **小内核、大边缘**：内核 7 个部件自己写；模型/渠道/Skill/Memory/MCP/插件都是薄适配。
3. **可度量**：每个 Phase 的验收都引用全局指标（见 0.6）。

### 0.3 明确不做

自研 LLM SDK、图引擎、向量库、Web UI、RAG 全家桶、多租户计费、插件市场、为对齐而复制类名。

### 0.4 技术栈

| 包 | 版本 | 用途 | 归属 |
|----|------|------|------|
| `langgraph` | ≥0.2,<0.3 | StateGraph + Checkpoint | 复用 |
| `langgraph-checkpoint-sqlite` | ≥2.0 | 持久化 | 复用 |
| `pydantic` / `pydantic-settings` | ≥2.6 / ≥2.2 | 数据与配置 | 复用 |
| `httpx` | ≥0.27 | 模型/MCP HTTP | 复用 |
| `pyyaml` | ≥6.0 | SKILL.md | 复用 |
| `opentelemetry-api/sdk` + `exporter-otlp` | ≥1.24 | Trace | 复用 |
| `prometheus-client` | ≥0.20 | Metrics | 复用 |
| `structlog` | ≥24.0 | 日志 | 复用 |
| `tenacity` | ≥8.2 | 重试 | 复用 |
| `tiktoken` | ≥0.6 | token 计数（可选降级为估算） | 复用 |
| `uvicorn` / `fastapi` | ≥0.29 / ≥0.110 | WebChat / Gateway | 复用 |

> 原则：能复用标准库/成熟包的不自研。自研的只有「三个框架各自缺、且决定强/快」的机制。

### 0.5 目录结构（core = 内核自研，edge = 薄适配）

```
Harness/
├── pyproject.toml
├── README.md
├── src/harness/
│   ├── __init__.py
│   ├── config/                    # edge：Pydantic Settings + .env
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   ├── message/                   # core
│   │   ├── __init__.py
│   │   ├── role.py
│   │   ├── content_block.py       # 5 种必需块 + 其余留接口
│   │   ├── msg.py
│   │   └── helpers.py             # 构造 User/Assistant/Tool/System
│   │
│   ├── context/                   # ★ core：效率核心
│   │   ├── __init__.py
│   │   ├── assembler.py           # 装配 + 前缀哈希
│   │   ├── cache_policy.py        # 按 Provider 打缓存断点
│   │   ├── prefix_guard.py        # 前缀变化原因白名单守卫
│   │   └── token_budget.py        # token 预算 + 触发压缩
│   │
│   ├── model/                     # edge（薄）
│   │   ├── __init__.py
│   │   ├── base.py                # Model ABC + 能力探测
│   │   ├── types.py               # ChatChunk / ChatResponse / GenerateOptions
│   │   ├── cache_profile.py       # 供应商缓存画像（explicit/automatic/none）
│   │   ├── openai_compat.py       # OpenAI 兼容（含 DeepSeek/Kimi/Ollama）
│   │   └── anthropic.py
│   │
│   ├── tool/                      # core + edge
│   │   ├── __init__.py
│   │   ├── base.py                # BaseTool + ToolResult
│   │   ├── reflective.py          # @tool 反射生成
│   │   ├── registry.py
│   │   ├── budget.py              # 结果截断 + 去重缓存
│   │   ├── executor.py            # 调度并行 + 重叠
│   │   ├── admission.py           # 批次准入（只读并行/写串行）
│   │   └── builtin/               # bash / file / http
│   │       └── __init__.py
│   │
│   ├── loop/                      # ★ core
│   │   ├── __init__.py
│   │   ├── state.py               # AgentState
│   │   ├── react_graph.py         # StateGraph 骨架
│   │   ├── streaming.py           # 流式 + 重叠工具调度
│   │   ├── recovery.py            # 三层自愈
│   │   ├── taint.py               # 轮次污染
│   │   ├── steering.py            # 中途插话
│   │   └── interrupt.py           # 中断
│   │
│   ├── session/                   # ★ core
│   │   ├── __init__.py
│   │   ├── entry.py               # SessionTreeEntry
│   │   ├── store.py               # SQLite entry 存储
│   │   ├── window.py              # 上下文窗口派生
│   │   └── checkpoint.py          # LangGraph checkpoint 封装
│   │
│   ├── permission/                # core
│   │   ├── __init__.py
│   │   ├── mode.py
│   │   ├── rule.py
│   │   └── engine.py
│   │
│   ├── hitl/                      # core
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   └── storage.py
│   │
│   ├── compaction/                # core
│   │   ├── __init__.py
│   │   ├── strategy.py            # 切点选择 + 摘要生成
│   │   └── summary.py             # 16K 上限 + 回放
│   │
│   ├── skill/                     # edge
│   │   ├── __init__.py
│   │   ├── model.py
│   │   ├── loader.py
│   │   ├── repository.py          # 四层合成
│   │   ├── trigger.py
│   │   └── activation.py          # 追加 custom_message，不改 system
│   │
│   ├── memory/                    # edge
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── in_memory.py
│   │   ├── session_view.py        # AgentState ↔ Memory
│   │   ├── long_term.py
│   │   └── tools.py               # Memory as Tool ★
│   │
│   ├── mcp/                       # edge
│   │   ├── __init__.py
│   │   └── client.py              # JSON-RPC stdio
│   │
│   ├── event/                     # core
│   │   ├── __init__.py
│   │   ├── types.py
│   │   └── bus.py
│   │
│   ├── observability/             # edge（封装）
│   │   ├── __init__.py
│   │   ├── tracing.py
│   │   ├── metrics.py
│   │   └── logging.py
│   │
│   ├── agent/                     # core
│   │   ├── __init__.py
│   │   ├── interface.py           # 四合一 Agent
│   │   ├── base.py
│   │   └── react_agent.py
│   │
│   ├── gateway/                   # edge
│   │   ├── __init__.py
│   │   ├── channel.py             # ChannelAdapter ABC
│   │   ├── router.py
│   │   ├── steering_api.py
│   │   ├── plugin_sdk.py
│   │   ├── server.py
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── webchat.py         # 实装
│   │       ├── feishu.py          # 壳 + 配置
│   │       └── mcp_stdio.py       # 壳 + 配置
│   │
│   └── extension/                 # edge
│       ├── __init__.py
│       ├── middleware.py          # Onion/Transformer/Notification
│       └── hook.py                # Pre/Post * + JsonlTraceExporter
├── examples/
│   ├── 01_basic.py
│   ├── 02_streaming_overlap.py
│   ├── 03_steering.py
│   ├── 04_hitl.py
│   ├── 05_skill_memory_mcp.py
│   └── 06_benchmark.py            # 对比基准（人眼可核的原始数值）
```

> `tests/` 不在项目初期创建。测试、基准采集器、质量任务集统一在阶段 G（P17）建立，避免项目根目录堆满与功能无关的文件。

### 0.6 全局运行时指标（所有 Phase 共用）

| 指标 | 目标 |
|------|------|
| `cache_hit_ratio` | ≥ 0.8（第 2 轮起） |
| `ttft_p50`（命中缓存） | < 1.5s |
| 3 只读工具墙钟 | ≤ 1.3 × 单工具 |
| 50 轮 `input_tokens` | < 32k 且平稳 |
| `resume_replayed_tools` | = 0 |
| `loop_recovery` 后模型调用数 | ≤ max_steps |
| `cache_hit_ratio_estimated` | ≥ 0.8（供应商不返回缓存字段时） |
| `task_success_rate` | ≥ 0.9（10 条固定任务，防「快但错」） |
  
> 指标采集器（benchmark + fake_provider）不在项目初期创建，统一在 P17 建立。在此之前各 Phase 只声明验收指标，不单独编写验收脚本；指标由 P17 的采集器统一度量。

### 0.7 每个 Phase 的交付清单（强制）

```
✅ 新增/修改文件（每个 ≤ 300 行，完整实现非 stub）
✅ 完整类型注解 + docstring
✅ 运行时指标输出（引用 0.6 中对应项）
✅ 文件清单（路径 + 行数）
✅ 等用户确认后才进入下一 Phase
```

---

## 阶段 A：地基

### Phase 0：最小可运行工程

**目标**：只保证「装得上、导得进、跑得动」，不写业务代码，也不建测试目录。

**依赖**：无

| 文件 | ≤行 | 内容 |
|------|----|------|
| `pyproject.toml` | 80 | 依赖 + 包配置 |
| `.gitignore` | 20 | — |
| `.env.example` | 60 | 模型/渠道/OTel 配置模板 |
| `src/harness/__init__.py` | 10 | 包声明与版本号 |

**运行时验收**：`pip install -e . --no-deps` 成功；`python -c "import harness; print(harness.__version__)"` 输出 `0.1.0`。

---

### Phase 1：消息模型 + ContentBlock

**目标**：全链路统一消息；content 为块数组；序列化字节稳定（缓存前提）。

**依赖**：Phase 0

| 文件 | ≤行 | 内容 |
|------|----|------|
| `message/role.py` | 30 | Role 枚举 |
| `message/content_block.py` | 220 | 5 种必需块 + 基类；其余留接口 |
| `message/msg.py` | 150 | Msg（id/role/name/content/metadata/timestamp/usage） |
| `message/helpers.py` | 80 | 构造 User/Assistant/Tool/System |
| `message/__init__.py` | 30 | 导出 |

**运行时验收**：同一 Msg 连续序列化 2 次，JSON 字节完全一致（为前缀稳定打基础）。

---

## 阶段 B：效率核心（强/快的差距主要在这里）

### Phase 2：上下文装配器 + Prompt 前缀缓存 ★

**目标**：装配请求；稳定前缀字节不变；按供应商能力打缓存断点。

**依赖**：Phase 1

| 文件 | ≤行 | 内容 |
|------|----|------|
| `context/assembler.py` | 250 | 分层装配（stable_prefix/history/volatile）+ prefix_hash |
| `context/cache_policy.py` | 150 | `CacheProfile` 驱动：explicit 打断点 / automatic 只保稳定 |
| `context/prefix_guard.py` | 120 | 前缀变化原因白名单，非白名单变化直接抛错 |
| `context/token_budget.py` | 120 | token 计数 + 超阈值标记 compaction_required |

**运行时验收**：
- 连续 3 轮装配，`prefix_hash` 完全一致
- 故意把时间戳塞进 `stable_prefix` → PrefixGuard 抛错
- 真实 Provider 可用时：第 2 轮 `cache_read_tokens > 0`

---

### Phase 3：Model 适配 + 能力探测

**目标**：统一 `stream()`；探测上下文窗口/缓存/结构化输出能力。

**依赖**：Phase 2

| 文件 | ≤行 | 内容 |
|------|----|------|
| `model/base.py` | 150 | Model ABC + 能力方法 |
| `model/types.py` | 150 | ChatChunk / ChatResponse / GenerateOptions / Usage |
| `model/cache_profile.py` | 120 | 供应商缓存画像：explicit / automatic / none + 最小可缓存长度 + 断点上限 |
| `model/openai_compat.py` | 250 | OpenAI 兼容流式（覆盖 DeepSeek/Kimi/通义/Ollama） |
| `model/anthropic.py` | 200 | Anthropic 流式 + cache_control |

**运行时验收**：mock SSE 流 → 正确解析 text/tool_use 增量；能力探测返回正确布尔值；DeepSeek 风格 profile 得 `mode=automatic` 且不产生 `cache_control`，Anthropic 得 `mode=explicit`。

---

### Phase 4：Tool 系统（反射 + 结果预算）

**目标**：`@tool` 反射生成；结果截断与去重。

**依赖**：Phase 1

| 文件 | ≤行 | 内容 |
|------|----|------|
| `tool/base.py` | 100 | BaseTool + ToolResult |
| `tool/reflective.py` | 200 | inspect 签名 → JSON Schema |
| `tool/registry.py` | 120 | 注册/查找/给 LLM 的描述 |
| `tool/budget.py` | 150 | 80KB 截断 + tool+args 结果缓存 + 重复引用 |
| `tool/builtin/__init__.py` | 200 | bash / read_file / write_file / http_get |

**运行时验收**：
- 写一个普通函数加 `@tool`，自动得到正确 parameters
- 200KB 输出 → 截断到 ≤80KB 且保留头尾
- 相同 tool+args 第二次调用不执行（命中缓存）

---

### Phase 5：ReAct Loop + 流式

**目标**：LangGraph StateGraph 跑通「装配 → 模型 → 工具 → 判定」。

**依赖**：Phase 2, 3, 4

| 文件 | ≤行 | 内容 |
|------|----|------|
| `loop/state.py` | 150 | AgentState（messages/step/max_steps/stopping/taint） |
| `loop/react_graph.py` | 250 | 构图：assemble → model → tools → finalize + 条件边 |
| `loop/streaming.py` | 200 | 流式转发 + 收集 tool_use |

**运行时验收**：mock 模型 → 2 轮工具调用 → 最终回复；流式事件按序发出。

---

### Phase 6：并行执行 + 流式重叠

**目标**：只读并行、写串行；工具参数齐了立即执行，不等整条回复。

**依赖**：Phase 4, 5

| 文件 | ≤行 | 内容 |
|------|----|------|
| `tool/admission.py` | 180 | 冲突组 + 并行/串行批次 |
| `tool/executor.py` | 230 | asyncio 并行 + 重叠调度 + 结果归并 |
| `loop/streaming.py`（扩展） | +80 | 流中触发 `schedule_overlapped_tool` |

**运行时验收**：
- 3 个只读工具（各 sleep 1s）墙钟 ≈ 1.2s（非 3s）
- 流式场景：工具在模型 finish 前就开始执行（日志时间戳证明）
- 写工具与只读工具不同批次

---

### Phase 7：循环自愈 + 轮次污染 + 中断

**目标**：三层自愈；taint 追踪；任意时刻中断。

**依赖**：Phase 5

| 文件 | ≤行 | 内容 |
|------|----|------|
| `loop/recovery.py` | 230 | 工具重复 / 连续报错 / 助手复读 / terminate |
| `loop/taint.py` | 100 | tainted 标记与传播 |
| `loop/interrupt.py` | 90 | 设置 stopping + 原因 |

**运行时验收**：
- 同一 tool+args 第 2 次 → 被拦并注入提示
- 助手连续两条高相似 → 注入提醒
- 连续失败触发 terminate，模型调用数 ≤ max_steps
- interrupt() 后当轮结束、返回中断原因

---

## 阶段 C：可靠与治理

### Phase 8：Session Entry + Checkpoint 恢复

**目标**：entry 不可变序列；压缩/重置为追加；崩溃续跑不重跑工具。

**依赖**：Phase 5

| 文件 | ≤行 | 内容 |
|------|----|------|
| `session/entry.py` | 120 | message/compaction/reset/custom |
| `session/store.py` | 200 | SQLite 追加写 + 查询 |
| `session/window.py` | 120 | 边界 + first_kept 派生 |
| `session/checkpoint.py` | 150 | 封装 langgraph-checkpoint-sqlite + 已完成工具集合 |

**运行时验收**：
- 写 10 条 entry → 读回顺序与字节一致
- 模拟 kill 后 resume → `replayed_tools == 0`
- compaction entry 不修改任何已有 entry

---

### Phase 9：Permission + HITL

**目标**：5 模式判定 + 自定义规则 + 人工确认暂停/恢复。

**依赖**：Phase 8

| 文件 | ≤行 | 内容 |
|------|----|------|
| `permission/mode.py` | 40 | 5 模式枚举 |
| `permission/rule.py` | 120 | 规则匹配（tool / args 条件） |
| `permission/engine.py` | 180 | 判定链 |
| `hitl/manager.py` | 200 | 暂停 → 存 → 通知 → 恢复 |
| `hitl/storage.py` | 120 | 挂起记录 |

**运行时验收**：EXPLORE 下 write_file → DENY；DEFAULT 下 bash rm → ASK → HITL 挂起 → 模拟允许 → 恢复继续。

---

### Phase 10：Compaction（追加式）

**目标**：超阈值生成摘要 entry，上下文回落到预算内且不破坏前缀。

**依赖**：Phase 2, 8

| 文件 | ≤行 | 内容 |
|------|----|------|
| `compaction/strategy.py` | 220 | 切点选择 + 调用摘要模型 |
| `compaction/summary.py` | 120 | 16K 硬上限 + 回放 |

**运行时验收**：50 轮构造 → 超阈值触发 → 追加 compaction entry → `input_tokens` 回落到 < 32k → 下一轮 prefix_hash 仅因新增 entry 变化（不重写旧内容）；**摘要请求复用同一装配前缀**（有 usage 时 `cache_read_tokens > 0`），压缩后第 2 轮前缀重新稳定。

---

## 阶段 D：可观测

### Phase 11：Event + OTel + Prometheus + 日志

**目标**：事件驱动观测；暴露缓存命中率等核心指标。

**依赖**：Phase 5, 8

| 文件 | ≤行 | 内容 |
|------|----|------|
| `event/types.py` | 120 | 10 种事件 |
| `event/bus.py` | 180 | 发布/订阅 |
| `observability/tracing.py` | 150 | OTel 初始化 + Span |
| `observability/metrics.py` | 180 | 0.6 的全部指标 + `/metrics` |
| `observability/logging.py` | 100 | structlog JSON |

**运行时验收**：跑一次完整 Loop → `/metrics` 出现 `harness_cache_hit_ratio`、`harness_ttft_seconds`；Trace 包含 model/tool span；日志为合法 JSON。

---

## 阶段 E：能力面（边缘，薄）

### Phase 12：Gateway（接口 + WebChat 实装 + 飞书/MCP 壳）

**目标**：渠道接口完整；WebChat 可用；飞书/MCP 只做壳 + 配置。

**依赖**：Phase 5, 7

| 文件 | ≤行 | 内容 |
|------|----|------|
| `gateway/channel.py` | 100 | ChannelAdapter ABC + RawMessage/SendResult |
| `gateway/router.py` | 180 | 入站路由 + 出站反向路由 |
| `gateway/server.py` | 220 | FastAPI：chat / steer / hitl / metrics / ws |
| `gateway/adapters/webchat.py` | 180 | WebSocket 实装 |
| `gateway/adapters/feishu.py` | 150 | 壳：challenge 校验 + send 骨架（配置驱动） |
| `gateway/adapters/mcp_stdio.py` | 120 | 壳：subprocess + JSON-RPC 骨架 |

**运行时验收**：WebSocket 发消息 → Agent → 回复回 WebSocket；飞书/MCP 未启用时不影响启动；填入配置后能加载。

---

### Phase 13：Skill 系统（追加式注入）

**目标**：SKILL.md 解析 + 四层合成 + 触发；**Skill 以 `custom_message` 追加，不改写系统提示**。

**依赖**：Phase 2

| 文件 | ≤行 | 内容 |
|------|----|------|
| `skill/model.py` | 80 | Skill 数据模型 |
| `skill/loader.py` | 130 | frontmatter + 正文 |
| `skill/repository.py` | 180 | 四层优先级 |
| `skill/trigger.py` | 130 | 触发匹配 |
| `skill/activation.py` | 100 | 生成 `harness.skill` 自定义 entry 并追加到会话 |

**运行时验收**：
- 放一个 code-reviewer → 命中 → 追加 `custom_message` entry
- 同一会话中途激活第二个 Skill → **`prefix_hash` 不变**，只有 history 增长
- 仅当 Skill 引入未注册的新工具时，事件标记 `toolset_changed` 并提示开新会话

---

### Phase 14：Memory as Tool

**目标**：长期记忆做成两个工具，LLM 自主检索/保存。

**依赖**：Phase 4, 8

| 文件 | ≤行 | 内容 |
|------|----|------|
| `memory/base.py` | 80 | Memory ABC |
| `memory/in_memory.py` | 80 | 短期 |
| `memory/session_view.py` | 100 | AgentState ↔ Memory |
| `memory/long_term.py` | 160 | SQLite 存储 + 关键词/时间检索 |
| `memory/tools.py` | 120 | `memory_search` / `memory_save` 两个 Tool |

**运行时验收**：LLM 在需要时调用 `memory_search` 命中历史；`memory_save` 后新会话可检索到。

---

### Phase 15：MCP 接入

**目标**：stdio JSON-RPC 调用任意 MCP Server。

**依赖**：Phase 4

| 文件 | ≤行 | 内容 |
|------|----|------|
| `mcp/client.py` | 220 | connect / tools/list / tools/call / close |

**运行时验收**：连官方示例 MCP Server → 列出工具 → 调用成功 → 注册进 Toolkit。

---

### Phase 16：扩展点（Middleware + Hook + Plugin）

**目标**：三种 Middleware 模式；阶段 Hook；运行时插件加载。

**依赖**：Phase 5, 9, 13

| 文件 | ≤行 | 内容 |
|------|----|------|
| `extension/middleware.py` | 200 | 基类 + Chain + 三模式 |
| `extension/hook.py` | 180 | Hook ABC + HookEventType + JsonlTraceExporter |
| `gateway/plugin_sdk.py` | 180 | importlib 加载 + 注册适配器/规则/Skill |

**运行时验收**：注册一个 Hook 能收到 Pre/Post Reasoning；JsonlTraceExporter 产出合法 JSONL；插件加载后 Router 中出现新适配器。

---

## 阶段 F：交付

### Phase 17：示例 + 基准报告

**目标**：可运行示例 + 与三框架机制对比的基准报告。

**依赖**：全部

| 文件 | ≤行 | 内容 |
|------|----|------|
| `examples/01_basic.py` | 80 | 基础对话 |
| `examples/02_streaming_overlap.py` | 100 | 流式重叠演示 |
| `examples/03_steering.py` | 100 | 中途插话 |
| `examples/04_hitl.py` | 120 | 人工确认 |
| `examples/05_skill_memory_mcp.py` | 120 | 三者组合 |
| `examples/06_benchmark.py` | 200 | 输出 0.6 指标 |
| `tests/benchmark.py` | 200 | 统一指标采集（本阶段才建 `tests/`） |
| `tests/fake_provider.py` | 180 | 按 `prefix_hash` 记账的假模型，无 Key 验证缓存 |
| `tests/eval_tasks.jsonl` | 40 | 10 条固定任务 + 期望工具序列（质量基线） |
| `README.md` | 200 | 快速开始 + 架构 + 指标说明 |

**运行时验收**：`python examples/06_benchmark.py` 输出完整指标 JSON，且 0.6 全部达标；`task_success_rate ≥ 0.9`（无真实 API Key 时用 mock 验证管道，有 Key 时输出真实数值）。

---

## 依赖关系

```
P0 环境+基准
 └─ P1 消息+ContentBlock
     ├─ P2 上下文装配+缓存 ★
     │   ├─ P3 Model
     │   │   └─ P5 Loop+流式
     │   │       ├─ P6 并行+重叠
     │   │       ├─ P7 自愈+taint+中断
     │   │       ├─ P8 Session+Checkpoint
     │   │       │   ├─ P9 Permission+HITL
     │   │       │   └─ P10 Compaction
     │   │       ├─ P11 Event+观测
     │   │       ├─ P12 Gateway
     │   │       └─ P16 扩展点
     │   └─ P13 Skill
     ├─ P4 Tool+结果预算
     │   ├─ P6 / P7
     │   ├─ P14 Memory as Tool
     │   └─ P15 MCP
     └─ P17 示例+基准（最后）
```

关键路径：**P0 → P1 → P2 → P3 → P5 → P6 → P8 → P17**

---

## 风险与应对

| # | 风险 | 应对 |
|---|------|------|
| 1 | Prompt 缓存需要真实供应商验证 | P2 以 `prefix_hash` 断言核对前缀一致性；P17 建立 fake_provider 与基准后才做自动评分，无 Key 时标注「管道验证通过，数值待真实环境」 |
| 2 | LangGraph API 变动 | 锁 `>=0.2,<0.3`；所有图操作集中在 `loop/react_graph.py`，便于替换 |
| 3 | 流式重叠实现的复杂度 | 先做「批次级并行」（P6 前半），再做「流内重叠」（P6 后半），分两次验收 |
| 4 | 压缩摘要质量 | 默认用轻量模型；摘要 16K 硬上限；保留最近 N 轮原文 |
| 5 | Skill 注入破坏缓存 | 改为「追加 `custom_message` entry」，只有引入新工具集才需新会话（P13 验收断言 `prefix_hash` 不变） |
| 6 | 飞书/MCP 壳无法端到端验证 | 壳只保证接口与配置加载；真实联调作为可选项，不阻塞主线 |
| 7 | Python 吞吐不及 TS OpenClaw | 不承诺 CPU 吞吐；承诺 token 成本、工具等待、长会话延迟不劣 |
| 8 | 供应商不返回缓存命中数据（国产模型常见） | 用 `cache_hit_ratio_estimated` + 跨轮 TTFT 交叉验证；不伪造真实值 |
| 9 | 自动缓存按块对齐，前缀短于阈值不命中 | `CacheProfile.min_cacheable_tokens` 参与判断；低于阈值时不承诺「省 token」 |

---

## 与设计文档的对照

| Phase | 设计文档部件 | 对应「强/快」点 |
|-------|-------------|----------------|
| P1 | 部件 1 | 序列化稳定（缓存基础） |
| P2 | 部件 0 ★ | **快：缓存命中** |
| P3 | 部件 4 | 强：多模型 + 能力探测 |
| P4 | 部件 5 | 快：结果预算省 token |
| P5 | 部件 6 | 强：ReAct 骨架 |
| P6 | 部件 6 + 7.1 | **快：重叠 + 并行** |
| P7 | 部件 7.2/7.3 | 强：不死循环 |
| P8 | 部件 8 | **强：崩溃续跑** |
| P9 | 部件 9 | 强：安全闸门 |
| P10 | 部件 10 | 快：上下文不爆 |
| P11 | 部件 14 | 强：可度量可定位 |
| P12 | 部件 2 | 强：多渠道 |
| P13 | 部件 11 | 强：专业能力按需激活且不破缓存 |
| P14 | 部件 12 | 强：跨会话记忆 |
| P15 | 部件 13 | 强：生态复用 |
| P16 | 部件 15 | 强：可扩展 |
| P17 | 附录 B | 证明「快」 |

---

**文档版本**：v2.1（自审修订）
**最后更新**：2026-11-06
