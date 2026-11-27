/** Webhook 管理页：登记订阅（密钥仅显一次）+ 脱敏列表 + 测试投递 + 投递记录。 */
<template>
  <div>
    <PageHeader title="Webhooks" subtitle="事件推送：登记回调地址后，harness 运行时事件会以 HMAC-SHA256 签名 POST 到你的服务">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" @click="showCreate = true">新建订阅</button>
      </template>
    </PageHeader>

    <div class="panel">
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="items.length === 0" class="empty">暂无订阅。新建后即可接收 harness 事件推送（会话、工具调用、模型流等）。</div>
      <table v-else class="key-table">
        <thead>
          <tr>
            <th>名称</th><th>回调 URL</th><th>密钥前缀</th><th>事件类型</th><th>创建时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in items" :key="w.id">
            <td class="bold">{{ w.name }}</td>
            <td class="mono url">{{ w.url }}</td>
            <td class="mono">{{ w.secret_prefix }}…</td>
            <td>
              <span v-if="w.event_types.length === 0" class="muted">全部事件</span>
              <span v-else class="pill">{{ w.event_types.length }} 类</span>
            </td>
            <td class="muted">{{ w.created_at }}</td>
            <td class="right">
              <button class="btn ghost sm" :disabled="testingId === w.id" @click="handleTest(w)">
                {{ testingId === w.id ? "测试中…" : "测试" }}
              </button>
              <button class="btn ghost sm" @click="openDeliveries(w)">投递记录</button>
              <button class="btn ghost sm danger" @click="handleDelete(w)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新建订阅弹窗 -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal">
        <h3>新建 Webhook 订阅</h3>
        <p class="muted">创建后生成签名密钥；每次投递携带 X-Harness-Signature: v1=HMAC-SHA256(secret, "{timestamp}.{body}")。</p>
        <label>
          <span>名称 *</span>
          <input v-model.trim="form.name" placeholder="如 ops-alert" />
        </label>
        <label>
          <span>回调 URL *</span>
          <input v-model.trim="form.url" placeholder="https://your-service.example.com/hook" />
        </label>
        <label>
          <span>事件类型（逗号分隔，留空 = 全部事件）</span>
          <input v-model.trim="form.eventTypes" placeholder="tool_end, session_end" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showCreate = false">取消</button>
          <button class="btn primary" :disabled="!form.name || !form.url || creating" @click="handleCreate">
            {{ creating ? "创建中…" : "创建" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 密钥展示弹窗（仅一次） -->
    <div v-if="plaintextOf" class="modal-backdrop">
      <div class="modal">
        <h3>请立即保存签名密钥</h3>
        <p class="muted">这是唯一一次展示，关闭后无法再查看；丢失只能删除订阅重建。</p>
        <div class="plaintext mono">{{ plaintextOf }}</div>
        <div class="modal-actions">
          <button class="btn ghost" @click="copyPlaintext">复制</button>
          <button class="btn primary" @click="plaintextOf = null">我已保存</button>
        </div>
      </div>
    </div>

    <!-- 投递记录弹窗 -->
    <div v-if="deliveriesOf" class="modal-backdrop" @click.self="deliveriesOf = null">
      <div class="modal wide">
        <h3>投递记录 — {{ deliveriesOf.name }}</h3>
        <div v-if="deliveriesLoading" class="empty">加载中…</div>
        <div v-else-if="deliveries.length === 0" class="empty">暂无投递记录。点"测试"可触发一次投递。</div>
        <table v-else class="key-table">
          <thead>
            <tr><th>事件</th><th>状态</th><th>状态码</th><th>尝试</th><th>耗时</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in deliveries" :key="d.id">
              <td class="mono">{{ d.event_type }}</td>
              <td><span class="pill" :class="d.status === 'success' ? 'ok' : 'err'">{{ d.status }}</span></td>
              <td class="mono">{{ d.status_code ?? "—" }}</td>
              <td>{{ d.attempts }}</td>
              <td class="muted">{{ d.duration_ms != null ? `${d.duration_ms}ms` : "—" }}</td>
              <td class="muted">{{ d.created_at }}</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn ghost" @click="deliveriesOf = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";

import { createWebhook, deleteWebhook, listWebhookDeliveries, listWebhooks, testWebhook } from "@/api/webhooks";
import type { WebhookDeliveryItem, WebhookItem } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const items = ref<WebhookItem[]>([]);
const loading = ref(false);
const showCreate = ref(false);
const creating = ref(false);
const testingId = ref<string | null>(null);
const form = reactive<{ name: string; url: string; eventTypes: string }>({
  name: "",
  url: "",
  eventTypes: "",
});
const plaintextOf = ref<string | null>(null);
const deliveriesOf = ref<WebhookItem | null>(null);
const deliveries = ref<WebhookDeliveryItem[]>([]);
const deliveriesLoading = ref(false);

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listWebhooks();
    items.value = data.items;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function handleCreate(): Promise<void> {
  creating.value = true;
  try {
    const types = form.eventTypes
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const data = await createWebhook({
      name: form.name,
      url: form.url,
      event_types: types.length > 0 ? types : null,
    });
    showCreate.value = false;
    form.name = "";
    form.url = "";
    form.eventTypes = "";
    plaintextOf.value = data.secret;
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "创建失败");
  } finally {
    creating.value = false;
  }
}

async function handleTest(w: WebhookItem): Promise<void> {
  testingId.value = w.id;
  try {
    const data = await testWebhook(w.id);
    const d = data.delivery;
    if (d.status === "success") {
      pushToast(`投递成功（HTTP ${d.status_code}，${d.attempts} 次尝试）`);
    } else {
      pushToast(`投递失败（HTTP ${d.status_code ?? "网络异常"}，已尝试 ${d.attempts} 次）`);
    }
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "测试失败");
  } finally {
    testingId.value = null;
  }
}

async function handleDelete(w: WebhookItem): Promise<void> {
  if (!confirm(`确认删除订阅 "${w.name}"？其投递记录会一并删除。`)) return;
  try {
    await deleteWebhook(w.id);
    pushToast("已删除");
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "删除失败");
  }
}

async function openDeliveries(w: WebhookItem): Promise<void> {
  deliveriesOf.value = w;
  deliveries.value = [];
  deliveriesLoading.value = true;
  try {
    const data = await listWebhookDeliveries(w.id);
    deliveries.value = data.items;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载投递记录失败");
  } finally {
    deliveriesLoading.value = false;
  }
}

async function copyPlaintext(): Promise<void> {
  if (!plaintextOf.value) return;
  try {
    await navigator.clipboard.writeText(plaintextOf.value);
    pushToast("已复制到剪贴板");
  } catch {
    pushToast("复制失败，请手动选中复制");
  }
}

void reload();
</script>

<style scoped>
.key-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.key-table th,
.key-table td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border, #e1e3e8);
}
.key-table th {
  color: var(--fg-dim, #666);
  font-weight: 500;
}
.right {
  text-align: right;
  white-space: nowrap;
}
.right .btn.sm + .btn.sm {
  margin-left: 6px;
}
.bold {
  font-weight: 600;
}
.mono {
  font-family: monospace;
}
.url {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.danger {
  color: #dc2626;
}
.plaintext {
  background: var(--panel-alt, #f8f9fb);
  border: 1px dashed var(--warn, #fbbf24);
  border-radius: 6px;
  padding: 12px;
  font-size: 14px;
  word-break: break-all;
  user-select: all;
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
  width: 480px;
  max-height: 85vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal.wide {
  width: 720px;
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
.modal input {
  padding: 6px 10px;
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  opacity: 0.6;
  font-size: 12px;
}
.empty {
  padding: 20px;
  text-align: center;
  opacity: 0.6;
  font-size: 13px;
}
.pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--panel-alt, #f3f4f6);
}
.pill.ok {
  color: #16a34a;
}
.pill.err {
  color: #dc2626;
}
</style>
