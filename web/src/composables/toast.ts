/** 极简 toast：全局队列 + 1.8s 自动消失。 */
import { reactive } from "vue";

export interface ToastItem {
  id: number;
  text: string;
}

const state = reactive<{ items: ToastItem[] }>({ items: [] });
let seq = 0;

/** 弹出一条提示。 */
export function pushToast(text: string, duration = 1800): void {
  const id = ++seq;
  state.items.push({ id, text });
  window.setTimeout(() => {
    const index = state.items.findIndex((item) => item.id === id);
    if (index >= 0) state.items.splice(index, 1);
  }, duration);
}

export const toastState = state;
