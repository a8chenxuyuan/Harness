/** 工具市场页：全量工具列表（内置+MCP）+ MCP server 注册 + 只读工具调试面板。 */
<template>
  <div>
    <PageHeader title="工具市场" subtitle="内置工具与外部 MCP server 工具的统一目录，只读工具可在线调试">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" @click="showRegister = true">注册 MCP Server</button>
      </template>
    </PageHeader>

    <div class="panel">
      <!-- MCP server 列表 -->
      <div class="section-title">已注册 MCP Server（{{ servers.length }}）</div>
      <div v-if="servers.length === 0" class="empty small">尚未注册外部 MCP Server。注册后其工具会自动接入下方市场。</div>
      <table v-else class="srv-table">
        <thead>
          <tr><th>名称</th><th>启动命令</th><th>工具数</th><th>注册时间</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="s in servers" :key="s.name">
            <td class="bold">{{ s.name }}</td>
            <td class="mono muted">{{ s.command }} {{ s.args.join(" ") }}</td>
            <td>{{ s.tool_count }}</td>
            <td class="muted">{{ s.registered_at }}</td>
            <td class="right">
              <button class="btn ghost sm" @click="handleDeleteServer(s)">注销</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 工具市场 -->
      <div class="section-title">工具目录（{{ items.length }}）</div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else class="tool-grid">
        <div v-for="tool in items" :key="tool.name" class="tool-card">
          <div class="card-head">
            <span class="name">{{ tool.name }}</span>
            <span class="pill" :class="tool.source === 'mcp' ? 'info' : 'ok'">{{ tool.source }}</span>
            <span class="pill" :class="tool.readonly ? 'ok' : 'err'">{{ tool.readonly ? "只读" : "写类" }}</span>
          </div>
          <div v-if="tool.server" class="muted via">via {{ tool.server }}</div>
          <div v-if="tool.description" class="desc">{{ tool.description }}</div>
          <div class="card-foot">
            <button class="btn ghost sm" :disabled="!tool.readonly" @click="openDebug(tool)">
              {{ tool.readonly ? "调试" : "写类不可调试" }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 注册 MCP server 弹窗 -->
    <div v-if="showRegister" class="modal-backdrop" @click.self="showRegister = false">
      <div class="modal">
        <h3>注册 MCP Server（stdio）</h3>
        <p class="muted">注册时会立即握手验证；失败返回错误，不会注册半可用实例。注册为内存态，重启后需重新注册。</p>
        <label>
          <span>名称 *</span>
          <input v-model.trim="reg.name" placeholder="如 filesystem" />
        </label>
        <label>
          <span>启动命令 *</span>
          <input v-model.trim="reg.command" placeholder="如 npx / uvx / python" />
        </label>
        <label>
          <span>命令行参数（每行一个）</span>
          <textarea v-model="argsText" rows="3" placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;/tmp"></textarea>
        </label>
        <label>
          <span>环境变量（每行 KEY=VALUE）</span>
          <textarea v-model="envText" rows="2" placeholder="API_KEY=xxx"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRegister = false">取消</button>
          <button class="btn primary" :disabled="!reg.name || !reg.command || registering" @click="handleRegister">
            {{ registering ? "注册中…" : "注册" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 调试弹窗 -->
    <div v-if="debugToolName" class="modal-backdrop" @click.self="debugToolName = null">
      <div class="modal">
        <h3>调试工具：{{ debugToolName }}</h3>
        <label>
          <span>入参（JSON 对象）</span>
          <textarea v-model="debugArgsText" rows="5" class="mono" placeholder='{"path": "README.md"}'></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="debugToolName = null">关闭</button>
          <button class="btn primary" :disabled="debugRunning" @click="runDebug">
            {{ debugRunning ? "执行中…" : "执行" }}
          </button>
        </div>
        <div v-if="debugResult" class="debug-result" :class="{ err: !debugResult.ok }">
          <div class="meta muted">
            {{ debugResult.ok ? "成功" : "失败" }} · {{ debugResult.execution_time_ms }}ms
          </div>
          <pre class="mono">{{ debugResult.error || debugResult.output || "(空输出)" }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

import {
  debugTool,
  deleteMcpServer,
  listMcpServers,
  listToolMarket,
  registerMcpServer,
} from "@/api/tools";
import type { McpServerItem, ToolDebugData, ToolMarketItem } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const items = ref<ToolMarketItem[]>([]);
const servers = ref<McpServerItem[]>([]);
const loading = ref(false);

const showRegister = ref(false);
const registering = ref(false);
const reg = ref({ name: "", command: "" });
const argsText = ref("");
const envText = ref("");

const debugToolName = ref<string | null>(null);
const debugArgsText = ref("{}");
const debugRunning = ref(false);
const debugResult = ref<ToolDebugData | null>(null);

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const [market, srv] = await Promise.all([listToolMarket(), listMcpServers()]);
    items.value = market.items;
    servers.value = srv.items;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function handleRegister(): Promise<void> {
  registering.value = true;
  try {
    await registerMcpServer({
      name: reg.value.name,
      command: reg.value.command,
      args: splitLines(argsText.value),
      env: parseEnv(envText.value),
    });
    pushToast(`MCP Server ${reg.value.name} 注册成功`);
    showRegister.value = false;
    reg.value = { name: "", command: "" };
    argsText.value = "";
    envText.value = "";
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "注册失败");
  } finally {
    registering.value = false;
  }
}

async function handleDeleteServer(s: McpServerItem): Promise<void> {
  if (!confirm(`确认注销 MCP Server "${s.name}"？其接入的 ${s.tool_count} 个工具会一并回收。`)) return;
  try {
    await deleteMcpServer(s.name);
    pushToast("已注销");
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "注销失败");
  }
}

function openDebug(tool: ToolMarketItem): void {
  debugToolName.value = tool.name;
  debugArgsText.value = "{}";
  debugResult.value = null;
}

async function runDebug(): Promise<void> {
  let args: Record<string, unknown>;
  try {
    args = JSON.parse(debugArgsText.value || "{}") as Record<string, unknown>;
  } catch {
    pushToast("入参不是合法 JSON");
    return;
  }
  debugRunning.value = true;
  try {
    debugResult.value = await debugTool(debugToolName.value!, args);
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "调试失败");
  } finally {
    debugRunning.value = false;
  }
}

function splitLines(text: string): string[] {
  return text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

function parseEnv(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const line of splitLines(text)) {
    const idx = line.indexOf("=");
    if (idx > 0) env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return env;
}

void reload();
</script>

<style scoped>
.section-title {
  font-weight: 600;
  margin: 8px 0 12px;
}
.srv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: 24px;
}
.srv-table th,
.srv-table td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border, #e1e3e8);
}
.srv-table th {
  color: var(--fg-dim, #666);
  font-weight: 500;
}
.right {
  text-align: right;
}
.bold {
  font-weight: 600;
}
.mono {
  font-family: monospace;
}
.empty.small {
  font-size: 13px;
  padding: 8px 0 20px;
}
.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.tool-card {
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--bg, #fff);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.card-head .name {
  font-weight: 600;
  font-size: 15px;
}
.via {
  font-size: 12px;
}
.desc {
  font-size: 13px;
  color: var(--fg-dim, #666);
}
.card-foot {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
}
.btn.sm {
  padding: 4px 10px;
  font-size: 12px;
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg, #fff);
  border-radius: 10px;
  padding: 24px;
  width: 520px;
  max-height: 85vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal h3 {
  margin: 0;
}
.modal label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.modal input,
.modal textarea {
  padding: 6px 10px;
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
}
.modal textarea.mono {
  font-family: monospace;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.debug-result {
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--panel-alt, #f8f9fb);
}
.debug-result.err {
  border-color: #f87171;
}
.debug-result .meta {
  margin-bottom: 6px;
}
.debug-result pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow-y: auto;
  font-size: 12px;
}
.muted {
  opacity: 0.6;
  font-size: 12px;
}
</style>
