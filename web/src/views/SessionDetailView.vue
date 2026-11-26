/** 会话详情页：消息列表 + 输入发送（真实后端走 /agents/run 落库）。 */
<template>
  <div>
    <PageHeader :title="session?.title ?? '会话详情'" :subtitle="subtitle">
      <template #actions>
        <button class="btn ghost" @click="router.push('/sessions')">返回列表</button>
        <button class="btn danger" @click="remove">删除</button>
      </template>
    </PageHeader>

    <div v-if="loading" class="panel loading">加载中…</div>
    <div v-else-if="error" class="panel loading">{{ error }}</div>

    <div v-else class="split">
      <div class="panel chat">
        <div ref="listRef" class="chat-body">
          <div v-if="messages.length === 0" class="empty">
            <div class="empty-icon">☰</div>
            <div class="empty-title">还没有消息</div>
            <p class="empty-desc">在下方输入问题，发送后会运行 Agent 并把用户消息与助手回答写入本会话。</p>
          </div>

          <div
            v-for="message in messages"
            :key="message.id"
            class="msg"
            :class="message.role"
          >
            <div class="msg-meta">
              <span class="who">{{ roleLabel(message.role) }}</span>
              <span class="mono faint">#{{ message.seq }}</span>
            </div>
            <div class="bubble">
              <template v-if="message.parts.length">
                <template v-for="(part, index) in message.parts" :key="index">
                  <p v-if="part.type === 'text'" class="part-text">{{ part.text }}</p>
                  <p v-else class="part-mono mono">
                    [{{ part.type }}] {{ part.name ?? "" }}{{ part.content ? ` · ${part.content}` : "" }}
                  </p>
                </template>
              </template>
              <p v-else class="part-text">{{ message.text }}</p>
            </div>
          </div>

          <div v-if="sending" class="msg assistant">
            <div class="msg-meta"><span class="who">助手</span><span class="mono faint">运行中…</span></div>
            <div class="bubble typing">正在运行 Agent…</div>
          </div>
        </div>

        <div class="composer">
          <textarea
            v-model="draft"
            rows="3"
            placeholder="输入消息，Ctrl + Enter 发送"
            :disabled="sending"
            @keydown.ctrl.enter.prevent="send"
            @keydown.meta.enter.prevent="send"
          ></textarea>
          <div class="composer-actions">
            <span class="faint">{{ messages.length }} 条消息</span>
            <button class="btn primary" :disabled="sending || !draft.trim()" @click="send">
              {{ sending ? "运行中…" : "发送" }}
            </button>
          </div>
        </div>
      </div>

      <div class="side-panel">
        <div class="panel mini">
          <h4>会话信息</h4>
          <p class="mono">GET /api/v1/sessions/{{ session?.session_id }}</p>
          <ul class="timeline">
            <li class="done"><b>status</b><span>{{ session?.status }}</span></li>
            <li class="done"><b>message_count</b><span>{{ session?.message_count }}</span></li>
            <li class="done"><b>created_at</b><span>{{ formatTime(session?.created_at) }}</span></li>
            <li class="done"><b>updated_at</b><span>{{ formatTime(session?.updated_at) }}</span></li>
          </ul>
        </div>
        <div class="panel mini">
          <h4>说明</h4>
          <p>发送消息会调用 POST /agents/run，由后端统一落 user / assistant 两条消息。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { listMessages, sendMessage } from "@/api/messages";
import { getSession, removeSession } from "@/api/sessions";
import type { ChatMessage, SessionDetail } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { pushToast } from "@/composables/toast";

const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const session = ref<SessionDetail | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const sending = ref(false);
const listRef = ref<HTMLElement | null>(null);

const subtitle = computed(() =>
  session.value
    ? `${session.value.session_id} · ${session.value.status} · ${session.value.message_count} 条消息`
    : "",
);

function sessionId(): string {
  return String(route.params.id);
}

async function reload(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [detail, list] = await Promise.all([
      getSession(sessionId()),
      listMessages(sessionId(), 0, 200),
    ]);
    session.value = detail;
    messages.value = list.items;
    await scrollToBottom();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function reloadMessages(): Promise<void> {
  const [detail, list] = await Promise.all([
    getSession(sessionId()),
    listMessages(sessionId(), 0, 200),
  ]);
  session.value = detail;
  messages.value = list.items;
  await scrollToBottom();
}

/** 发送消息：后端运行 Agent 并落 user / assistant 消息。 */
async function send(): Promise<void> {
  const text = draft.value.trim();
  if (!text || sending.value) return;

  sending.value = true;
  try {
    const result = await sendMessage(sessionId(), text);
    draft.value = "";
    if (result.status !== "success" && result.status !== "completed") {
      const reason = typeof result.metrics?.error === "string" ? result.metrics.error : "运行失败";
      pushToast(reason);
    }
    await reloadMessages();
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "发送失败");
  } finally {
    sending.value = false;
  }
}

async function remove(): Promise<void> {
  if (!window.confirm("确认删除该会话？")) return;
  try {
    await removeSession(sessionId());
    pushToast("已删除");
    await router.push("/sessions");
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "删除失败");
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = listRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function roleLabel(role: string): string {
  if (role === "user") return "我";
  if (role === "assistant") return "助手";
  if (role === "tool") return "工具";
  return "系统";
}

function formatTime(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

onMounted(reload);
</script>

<style scoped>
.loading {
  padding: 40px;
  text-align: center;
  color: var(--faint);
}

.chat {
  display: flex;
  flex-direction: column;
  min-height: 520px;
}

.chat-body {
  flex: 1;
  max-height: 560px;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-width: 86%;
}

.msg.user {
  align-self: flex-end;
  align-items: flex-end;
}

.msg-meta {
  display: flex;
  gap: 7px;
  align-items: baseline;
  font-size: 11px;
  color: var(--faint);
}

.msg-meta .who {
  color: var(--muted);
  font-weight: 550;
}

.bubble {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 13px;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.user .bubble {
  background: rgba(99, 102, 241, 0.14);
  border-color: rgba(99, 102, 241, 0.32);
}

.part-text {
  margin: 0;
}

.part-text + .part-text {
  margin-top: 8px;
}

.part-mono {
  margin: 6px 0 0;
  font-size: 11.5px;
  color: var(--muted);
}

.typing {
  color: var(--muted);
}

.composer {
  border-top: 1px solid var(--line-soft);
  padding: 12px 16px;
}

.composer textarea {
  width: 100%;
  resize: vertical;
  min-height: 68px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  padding: 10px 12px;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  outline: none;
}

.composer textarea:focus {
  border-color: rgba(99, 102, 241, 0.6);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 9px;
  font-size: 11px;
}

.mini {
  padding: 14px 16px;
}

.mini h4 {
  margin: 0 0 3px;
  font-size: 12px;
  font-weight: 580;
}

.mini p {
  margin: 0;
  color: var(--faint);
  font-size: 11.5px;
  line-height: 1.7;
}
</style>
