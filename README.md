# Harness

Prompt 缓存优先的 Python Agent 运行时。目标：比 LangGraph / AgentScope / OpenClaw
**更强、更快**。核心手段是**stable_prefix**——把 system prompt + tool schema
在会话开始时定型成**字节不变的稳定前缀**，让供应商自动 prompt cache 跨轮命中，
token 成本与首 token 延迟不随轮次上涨。

## 安装

```bash
git clone <repo> && cd Harness
pip install -e .           # 核心依赖
pip install -e ".[dev]"     # + pytest / ruff / mypy
```

## 快速开始

```bash
# 无真实 API Key → graceful skip（打印提示并 exit 0）
python examples/01_basic.py

# 配好 .env 或环境变量后跑
# MODEL__PROVIDER=deepseek MODEL__BASE_URL=https://api.deepseek.com/v1 \
# MODEL__API_KEY=sk-xxx MODEL__MODEL=deepseek-chat \
python examples/01_basic.py
```

6 个 example 覆盖 roadmap Phase 1-17 的全部核心机制：

| # | 文件 | 演示 |
|---|------|------|
| 01 | `examples/01_basic.py` | 基础对话 + graceful skip |
| 02 | `examples/02_streaming_overlap.py` | Phase 6 并行：3×sleep 墙钟 ≈ 1s（不是 3s） |
| 03 | `examples/03_steering.py` | Phase 7 中途插话 `agent.steer()` |
| 04 | `examples/04_hitl.py` | Phase 9 DEFAULT → ASK → HITL pending → approve |
| 05 | `examples/05_skill_memory_mcp.py` | Phase 13/14/15 三者组合（无 MCP server graceful skip） |
| 06 | `examples/06_benchmark.py` | roadmap §0.6 的 8 个全局指标，无 Key 时 fake_provider 管道验证 |

## 架构

```
src/harness/
├── agent/          # ★ core: Agent ABC + ReActAgent 主实现
├── config/          # edge: Pydantic Settings + .env 加载
├── message/         # ★ core: Msg + ContentBlock + Role
├── context/         # ★ core: ContextAssembler + prefix_hash + TokenBudget
├── model/           # edge: Model ABC + OpenAICompat / Anthropic + types
├── tool/            # core+edge: BaseTool + ReflectiveTool + ToolRegistry + 内置 4 工具
├── loop/            # ★ core: AgentState + run_loop + streaming + recovery + taint + interrupt
├── session/         # ★ core: SessionTree + SQLite store + Checkpoint
├── permission/      # core: 5 模式 PermissionEngine + 自定义规则
├── hitl/            # core: HitlManager + asyncio.Event 等待
├── compaction/      # core: 追加式压缩 + 16K 硬上限 + 回放
├── skill/           # edge: Skill + Loader + Repository + Trigger + Activator
├── memory/          # edge: InMemory + LongTerm(SQLite) + create_memory_tools
├── mcp/             # edge: McpClient (JSON-RPC 2.0 over stdio)
├── event/           # core: EventType + EventBus (async 订阅/发布)
├── observability/   # edge: OTel tracing + Prometheus metrics + structlog
├── gateway/         # edge: FastAPI server + WebChat + 飞书壳 + MCP stdio 壳
└── extension/       # edge: Middleware + Hook + JsonlTraceExporter
```

## 全局运行时指标（roadmap §0.6）

| 指标 | 目标 | 说明 |
|------|------|------|
| `cache_hit_ratio` | ≥ 0.8（第 2 轮起） | stable_prefix 命中供应商自动缓存的比例 |
| `ttft_p50` | < 1.5s | 命中缓存时的首 token 延迟 |
| 3 只读工具墙钟 | ≤ 1.3 × 单工具 | Phase 6 并行效果 |
| 50 轮 `input_tokens` | < 32k 且平稳 | Phase 10 compaction 效果 |
| `resume_replayed_tools` | = 0 | Phase 8 checkpoint 恢复不重跑工具 |
| `loop_recovery` 后模型调用数 | ≤ max_steps | Phase 7 自愈不无限循环 |
| `cache_hit_ratio_estimated` | ≥ 0.8 | 供应商不返回缓存字段时的估算 |
| `task_success_rate` | ≥ 0.9 | 10 条固定任务质量基线 |

跑 benchmark：

```bash
pytest tests/benchmark.py -v            # 无 Key：5 passed, 2 skipped
python examples/06_benchmark.py         # 输出 8 指标 JSON
```

## 依赖

来自 `pyproject.toml`：

| 包 | 版本 | 用途 | 归属 |
|----|------|------|------|
| `langgraph` | ≥0.2,<0.3 | StateGraph + Checkpoint | 复用 |
| `langgraph-checkpoint-sqlite` | ≥2.0 | 持久化 | 复用 |
| `pydantic` / `pydantic-settings` | ≥2.6 / ≥2.2 | 数据与配置 | 复用 |
| `httpx` | ≥0.27 | 模型/MCP HTTP | 复用 |
| `opentelemetry-*` | ≥1.24 | Trace | 复用 |
| `prometheus-client` | ≥0.20 | Metrics | 复用 |
| `structlog` | ≥24.0 | 日志 | 复用 |
| `tenacity` | ≥8.2 | 重试 | 复用 |
| `tiktoken` | ≥0.6 | token 计数 | 复用 |
| `uvicorn` / `fastapi` | ≥0.29 / ≥0.110 | WebChat / Gateway | 复用 |

## 目录结构

参见 `docs/implementation-roadmap.md` §0.5。完整设计见 `docs/framework-design.md`。

## 注意事项

- **无真实 API Key 时 examples 自动 graceful skip**（打印提示 + exit 0），不会 traceback
- **FakeModel 用 `ContextAssembler.prefix_hash` 记账**——这是 Phase 17 的验收核心，
  ContextAssembler 坏了 FakeModel 的缓存命中率就错了
- **pytest-asyncio 默认 fixture loop scope**：pyproject.toml 已设 `asyncio_mode = auto`

## License

TBD
