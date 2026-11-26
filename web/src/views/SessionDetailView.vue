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
            v-for="message in visibleMessages"
            :key="message.id"
            class="msg"
            :class="message.role"
          >
            <div class="msg-meta">
              <span class="who">{{ roleLabel(message.role) }}</span>
              <span v-if="message.status === 'failed'" class="msg-status failed">生成失败</span>
              <span v-else-if="message.status === 'cancelled'" class="msg-status cancelled">已取消</span>
              <span class="mono faint">
                {{ message.seq > 0 ? `#${message.seq}` : "流式" }}
              </span>
            </div>
            <div class="bubble">
              <template v-if="message.parts.length">
                <template v-for="(part, index) in message.parts" :key="index">
                  <p v-if="part.type === 'text'" class="part-text">{{ part.text }}</p>
                  <div
                    v-else-if="part.type === 'tool_call'"
                    class="tool-call"
                    :class="{ failed: part.ok === false }"
                  >
                    <div class="tool-head">
                      <span class="tool-name mono">工具 · {{ part.name }}</span>
                      <span class="tool-state">
                        {{ part.ok === undefined ? "运行中…" : part.ok ? "完成" : "失败" }}
                      </span>
                    </div>
                    <pre v-if="hasArgs(part)" class="tool-args mono">{{ prettyArgs(part) }}</pre>
                    <pre v-if="part.content" class="tool-output mono">{{ part.content }}</pre>
                  </div>
                  <p v-else class="part-mono mono">
                    [{{ part.type }}] {{ part.name ?? "" }}{{ part.content ? ` · ${part.content}` : "" }}
                  </p>
                </template>
                <span v-if="message.status === 'streaming'" class="caret"></span>
              </template>
              <p v-else class="part-text">
                {{ message.text || (message.status === "streaming" ? "正在生成…" : "") }}
              </p>
            </div>
            <div v-if="canAct(message)" class="msg-actions">
              <button class="btn ghost mini" :disabled="acting" @click="retry(message)">
                重试
              </button>
              <button class="btn ghost mini" :disabled="acting" @click="branch(message)">
                分支
              </button>
            </div>
          </div>

          <div v-if="streamError" class="stream-error">
            流式运行失败：{{ streamError }}
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
            <div class="composer-buttons">
              <button
                v-if="sending"
                class="btn ghost mini"
                :disabled="stopping"
                @click="stopStream"
              >
                {{ stopping ? "停止中…" : "停止" }}
              </button>
              <button class="btn primary" :disabled="sending || !draft.trim()" @click="send">
                {{ sending ? "运行中…" : "发送" }}
              </button>
            </div>
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
          <p>发送消息会调用 POST /agents/run/stream，后端流式生成并增量落 user / assistant 两条消息。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { branchMessage, listMessages, retryMessage } from "@/api/messages";
import { getSession, removeSession } from "@/api/sessions";
import type { ChatMessage, MessagePart, SessionDetail } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { useChatStream } from "@/composables/useChatStream";
import { pushToast } from "@/composables/toast";

const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const acting = ref(false);
const session = ref<SessionDetail | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const listRef = ref<HTMLElement | null>(null);

const {
  active: sending,
  error: streamError,
  message: streamingMessage,
  stopping,
  stop: stopStream,
  send: sendStream,
} = useChatStream(sessionId);

const subtitle = computed(() =>
  session.value
    ? `${session.value.session_id} · ${session.value.status} · ${session.value.message_count} 条消息`
    : "",
);

const visibleMessages = computed(() =>
  streamingMessage.value
    ? [...messages.value, streamingMessage.value]
    : messages.value,
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

/** 发送消息：SSE 流式渲染，结束后以服务端消息列表为准刷新。 */
async function send(): Promise<void> {
  const text = draft.value.trim();
  if (!text || sending.value) return;
  draft.value = "";
  await submit(text);
}

/** 用指定文本发起一次流式发送（发送与重试共用）。 */
async function submit(text: string): Promise<void> {
  if (!text.trim() || sending.value) return;

  await sendStream(text, {
    onUserMessage: (content) => {
      // 乐观回显用户消息，避免等待元数据期间输入内容消失
      messages.value = [
        ...messages.value,
        {
          id: `local-${Date.now()}`,
          session_id: sessionId(),
          role: "user",
          parts: [{ type: "text", text: content }],
          text: content,
          seq: messages.value.length + 1,
          parent_id: null,
          status: "completed",
          created_at: new Date().toISOString(),
        },
      ];
      void scrollToBottom();
    },
    onProgress: () => void scrollToBottom(),
    onSettled: reloadMessages,
    onError: (reason) => pushToast(reason),
  });
}

/** 失败 / 取消的助手消息可重试或派生分支。 */
function canAct(message: ChatMessage): boolean {
  return (
    message.role === "assistant" &&
    (message.status === "failed" || message.status === "cancelled") &&
    !sending.value
  );
}

/** 重试：后端软删旧问答并返回原文，前端重新走 SSE。 */
async function retry(message: ChatMessage): Promise<void> {
  if (sending.value || acting.value) return;
  acting.value = true;
  try {
    const data = await retryMessage(sessionId(), message.id);
    await reloadMessages();
    await submit(data.text);
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "重试失败");
  } finally {
    acting.value = false;
  }
}

/** 分支：复制历史到新会话并跳转。 */
async function branch(message: ChatMessage): Promise<void> {
  if (sending.value || acting.value) return;
  acting.value = true;
  try {
    const data = await branchMessage(sessionId(), message.id);
    pushToast(`已创建分支会话（${data.message_count} 条消息）`);
    await router.push(`/sessions/${data.session_id}`);
  } catch (err) {
    pushToast(err instanceof Error ? err.message : "分支失败");
  } finally {
    acting.value = false;
  }
}

function hasArgs(part: MessagePart): boolean {
  return !!part.arguments && Object.keys(part.arguments).length > 0;
}

function prettyArgs(part: MessagePart): string {
  return JSON.stringify(part.arguments ?? {}, null, 2);
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

// 分支会跳转到同一路由的新会话，组件被复用，需要按 id 变化重新拉取
watch(
  () => route.params.id,
  (next, previous) => {
    if (next && next !== previous) void reload();
  },
);
</script>

<style scoped src="./SessionDetailView.css"></style>
