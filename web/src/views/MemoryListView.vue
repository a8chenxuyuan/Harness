/** Memory 管理页：搜索 + 分页 + 手动保存 + 删除。 */
<template>
  <div>
    <PageHeader title="员工记忆" subtitle="员工跨对话记住的你的偏好与信息，可查看、搜索与纠正">
      <template #actions>
        <button class="btn ghost" :disabled="loading" @click="reload">刷新</button>
        <button class="btn primary" @click="showSave = true">手动保存</button>
      </template>
    </PageHeader>

    <div class="panel">
      <!-- 搜索栏 -->
      <div class="filters">
        <label>
          <span>关键词</span>
          <input v-model.trim="keyword" placeholder="空则返回全部" @keyup.enter="search" />
        </label>
        <label>
          <span>会话</span>
          <input v-model.trim="sessionFilter" placeholder="空=全部" />
        </label>
        <div class="filter-actions">
          <button class="btn ghost" @click="reset">重置</button>
          <button class="btn primary" @click="search">查询</button>
        </div>
      </div>

      <!-- 表格 -->
      <table class="table">
        <thead>
          <tr>
            <th>内容</th>
            <th>来源会话</th>
            <th>标签</th>
            <th>时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="empty">加载中…</td>
          </tr>
          <tr v-else-if="items.length === 0">
            <td colspan="5" class="empty">员工还没有记住任何内容。对话中它学到的东西会自动出现在这里。</td>
          </tr>
          <template v-else v-for="item in items" :key="item.item_id">
            <tr>
              <td class="content-cell" :title="item.content">{{ truncate(item.content, 120) }}</td>
              <td class="mono ellipsis">{{ item.session_id || "全局" }}</td>
              <td>
                <span v-if="item.tags.length" class="tags">
                  <span class="chip" v-for="t in item.tags" :key="t">{{ t }}</span>
                </span>
                <span v-else class="muted">—</span>
              </td>
              <td class="mono nowrap">{{ formatTime(item.created_at) }}</td>
              <td>
                <button class="btn ghost sm" @click="handleDelete(item.item_id)">删除</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <!-- 分页 -->
      <div class="foot">
        共 {{ total }} 条
        <div class="pager">
          <span :class="{ disabled: offset <= 0 }" @click="go(offset - limit)">‹</span>
          <span class="on">{{ page }}</span>
          <span :class="{ disabled: offset + limit >= total }" @click="go(offset + limit)">›</span>
        </div>
      </div>
    </div>

    <!-- 保存弹窗 -->
    <div v-if="showSave" class="modal-backdrop" @click.self="showSave = false">
      <div class="modal">
        <h3>手动添加记忆</h3>
        <p class="muted">用户主动存的记忆不需要审核，保存后 Agent 的 memory_search 立即可检索到。</p>
        <label>
          <span>内容 *</span>
          <textarea v-model="saveForm.content" rows="4" placeholder="要记住的信息…"></textarea>
        </label>
        <label>
          <span>来源会话（可选）</span>
          <input v-model.trim="saveForm.session_id" placeholder="空=全局记忆" />
        </label>
        <label>
          <span>标签（回车分隔，可选）</span>
          <textarea v-model="tagsText" rows="2" placeholder="work&#10;client_a"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" @click="showSave = false">取消</button>
          <button class="btn primary" :disabled="!saveForm.content.trim() || saving" @click="handleSave">
            {{ saving ? "保存中…" : "保存" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";

import { deleteMemory, listMemories, saveMemory } from "@/api/memories";
import type { MemoryItem } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const items = ref<MemoryItem[]>([]);
const total = ref(0);
const keyword = ref("");
const sessionFilter = ref("");
const loading = ref(false);
const limit = 20;
const offset = ref(0);

const showSave = ref(false);
const saving = ref(false);
const tagsText = ref("");
const saveForm = reactive({ content: "", session_id: "" });

const page = computed(() => Math.floor(offset.value / limit) + 1);

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const data = await listMemories({
      keyword: keyword.value.trim() || undefined,
      session_id: sessionFilter.value.trim() || null,
      limit,
      offset: offset.value,
    });
    items.value = data.items;
    total.value = data.total;
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "加载失败");
  } finally {
    loading.value = false;
  }
}

async function search(): Promise<void> {
  offset.value = 0;
  await reload();
}

function reset(): void {
  keyword.value = "";
  sessionFilter.value = "";
  void search();
}

function go(newOffset: number): void {
  if (newOffset < 0 || newOffset >= total.value) return;
  offset.value = newOffset;
  void reload();
}

async function handleSave(): Promise<void> {
  if (!saveForm.content.trim()) return;
  saving.value = true;
  try {
    await saveMemory({
      content: saveForm.content.trim(),
      session_id: saveForm.session_id.trim() || null,
      tags: splitLines(tagsText.value),
    });
    pushToast("记忆已保存");
    showSave.value = false;
    saveForm.content = "";
    saveForm.session_id = "";
    tagsText.value = "";
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

async function handleDelete(itemId: string): Promise<void> {
  if (!confirm("确认删除这条记忆？")) return;
  try {
    await deleteMemory(itemId);
    pushToast("已删除");
    await reload();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "删除失败");
  }
}

function truncate(text: string, n: number): string {
  return text.length > n ? text.slice(0, n) + "…" : text;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function splitLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

void reload();
</script>

<style scoped>
.content-cell {
  max-width: 360px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.chip {
  background: var(--panel-alt, #f0f2f5);
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 12px;
}
.muted {
  opacity: 0.6;
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
.modal input,
.modal textarea {
  padding: 6px 10px;
  border: 1px solid var(--border, #e1e3e8);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
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
