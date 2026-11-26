/** 会话流式发送：维护打字机文本、工具块、错误态、取消与结束刷新。 */
import { computed, ref } from "vue";

import { cancelStreamRun, streamMessage } from "@/api/messages";
import type { ChatMessage, MessagePart, StreamToolData } from "@/api/types";

export interface ChatStreamOptions {
  /** 流开始前的用户消息回显（由页面决定插入位置）。 */
  onUserMessage?: (content: string) => void;
  /** 每次增量或工具事件后的滚动等副作用。 */
  onProgress?: () => void;
  /** 流结束后的刷新（成功与失败都会执行）。 */
  onSettled?: () => Promise<void>;
  /** 失败提示（刷新完成后触发）。 */
  onError?: (message: string) => void;
}

export function useChatStream(sessionId: () => string) {
  const active = ref(false);
  const text = ref("");
  const parts = ref<MessagePart[]>([]);
  const error = ref("");
  const runId = ref("");
  const stopping = ref(false);
  const cancelled = ref(false);
  const toolIndex = new Map<string, number>();

  /** 流式中的助手消息（页面追加到消息列表尾部）。 */
  const message = computed<ChatMessage | null>(() => {
    if (!active.value) return null;
    return {
      id: "streaming",
      session_id: sessionId(),
      role: "assistant",
      parts: parts.value,
      text: text.value,
      seq: -1,
      parent_id: null,
      status: "streaming",
      created_at: null,
    };
  });

  /** 发送一条消息并消费 SSE 事件。 */
  async function send(
    input: string,
    options: ChatStreamOptions = {},
  ): Promise<void> {
    const content = input.trim();
    if (!content || active.value) return;

    reset();
    active.value = true;
    options.onUserMessage?.(content);

    try {
      await streamMessage(sessionId(), content, {
        onStart: (data) => {
          runId.value = data.run_id;
        },
        onDelta: (delta) => {
          appendDelta(delta);
          options.onProgress?.();
        },
        onTool: (data) => {
          applyToolEvent(data);
          options.onProgress?.();
        },
        onEnd: (data) => {
          if (data.status === "failed") error.value = data.error || "运行失败";
          if (data.status === "cancelled") cancelled.value = true;
        },
        onError: (reason) => {
          error.value = reason;
        },
      });
    } catch (err) {
      error.value = err instanceof Error ? err.message : "发送失败";
    } finally {
      // 先刷新再收起流式气泡，避免出现重复的用户消息
      try {
        await options.onSettled?.();
      } catch {
        // 刷新失败时保留本地内容，下一次进入页面会重新拉取
      }
      active.value = false;
      if (error.value) options.onError?.(error.value);
    }
  }

  /** 停止当前流式生成：服务端在下一个事件前收尾并推送 cancelled。 */
  async function stop(): Promise<void> {
    if (!active.value || !runId.value || stopping.value) return;
    stopping.value = true;
    try {
      await cancelStreamRun(runId.value);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "取消失败";
    } finally {
      stopping.value = false;
    }
  }

  function reset(): void {
    text.value = "";
    parts.value = [];
    error.value = "";
    runId.value = "";
    stopping.value = false;
    cancelled.value = false;
    toolIndex.clear();
  }

  /** 追加文本增量：并入最后一个 text 块，形成打字机效果。 */
  function appendDelta(delta: string): void {
    if (!delta) return;
    text.value += delta;
    const last = parts.value[parts.value.length - 1];
    if (last && last.type === "text") {
      last.text = `${last.text ?? ""}${delta}`;
    } else {
      parts.value.push({ type: "text", text: delta });
    }
  }

  /** 工具事件：start 占位，end 回填结果。 */
  function applyToolEvent(data: StreamToolData): void {
    if (data.status === "start") {
      for (const call of data.calls ?? []) {
        parts.value.push({
          type: "tool_call",
          name: call.name ?? "",
          arguments: call.arguments ?? {},
          content: "运行中…",
          ok: undefined,
        });
        toolIndex.set(call.id ?? call.name ?? "", parts.value.length - 1);
      }
      return;
    }
    for (const result of data.results ?? []) {
      const index = toolIndex.get(result.id ?? result.name ?? "");
      const target = index === undefined ? undefined : parts.value[index];
      if (!target) continue;
      target.ok = result.ok;
      target.content = (result.ok ? result.output : result.error) || "";
      target.execution_time_ms = result.execution_time_ms;
    }
  }

  return {
    active,
    text,
    parts,
    error,
    message,
    runId,
    stopping,
    cancelled,
    reset,
    send,
    stop,
  };
}
