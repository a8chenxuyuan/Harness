/** API Key 管理页：签发（明文仅显一次）+ 脱敏列表 + 吊销。 */
<template>
  <div>
    <PageHeader title="API Key" subtitle="机器调用凭据：外部程序用 Authorization: Bearer hk_... 直接调 API，无需登录">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" @click="showCreate = true">签发 Key</button>
      </template>
    </PageHeader>

    <div class="panel">
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="items.length === 0" class="empty">暂无 API Key。签发后外部程序即可用 hk_ key 机器调用本系统。</div>
      <table v-else class="key-table">
        <thead>
          <tr>
            <th>名称</th><th>Key 前缀</th><th>状态</th><th>最近使用</th><th>过期时间</th><th>创建时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="k in items" :key="k.id">
            <td class="bold">{{ k.name }}</td>
            <td class="mono">{{ k.key_prefix }}…</td>
            <td>
              <span class="pill" :class="k.is_active ? 'ok' : 'err'">{{ k.is_active ? "启用" : "已吊销" }}</span>
            </td>
            <td class="muted">{{ k.last_used_at || "从未使用" }}</td>
            <td class="muted">{{ k.expires_at || "永不过期" }}</td>
            <td class="muted">{{ k.created_at }}</td>
            <td class="right">
              <button class="btn ghost sm" :disabled="!k.is_active" @click="handleRevoke(k)">
                {{ k.is_active ? "吊销" : "已吊销" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 签发表单弹窗 -->
    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <div class="modal">
        <h3>签发 API Key</h3>
        <p class="muted">明文只在创建后显示一次，服务端只存哈希；丢失只能吊销重签。</p>
        <label>
          <span>名称 *</span>
          <input v-model.trim="form.name" placeholder="如 ci-pipeline / bot-runner" />
        </label>
        <label>
          <span>有效期（天，留空=永不过期）</span>
          <input v-model.number="form.expiresInDays" type="number" min="1" max="3650" placeholder="30" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showCreate = false">取消</button>
          <button class="btn primary" :disabled="!form.name || creating" @click="handleCreate">
            {{ creating ? "签发中…" : "签发" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 明文展示弹窗（仅一次） -->
    <div v-if="plaintextOf" class="modal-backdrop">
      <div class="modal">
        <h3>请立即保存你的 Key</h3>
        <p class="muted">这是唯一一次展示明文，关闭后无法再查看。泄露请立即吊销。</p>
        <div class="plaintext mono">{{ plaintextOf }}</div>
        <div class="modal-actions">
          <button class="btn ghost" @click="copyPlaintext">复制</button>
          <button class="btn primary" @click="plaintextOf = null">我已保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";

import { createApiKey, listApiKeys, revokeApiKey } from "@/api/apikeys";
import type { ApiKeyItem } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const items = ref<ApiKeyItem[]>([]);
const loading = ref(false);
const showCreate = ref(false);
const creating = ref(false);
const form = reactive<{ name: string; expiresInDays: number | null }>({
  name: "",
  expiresInDays: null,
});
const plaintextOf = ref<string | null>(null);

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listApiKeys();
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
    const days = form.expiresInDays;
    const data = await createApiKey({
      name: form.name,
      expires_in_days: days && days > 0 ? days : null,
    });
    showCreate.value = false;
    form.name = "";
    form.expiresInDays = null;
    plaintextOf.value = data.plaintext;
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "签发失败");
  } finally {
    creating.value = false;
  }
}

async function handleRevoke(k: ApiKeyItem): Promise<void> {
  if (!confirm(`确认吊销 API Key "${k.name}"（${k.key_prefix}…）？吊销后使用它的程序会立即 401。`)) return;
  try {
    await revokeApiKey(k.id);
    pushToast("已吊销");
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "吊销失败");
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
}
.bold {
  font-weight: 600;
}
.mono {
  font-family: monospace;
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
</style>
