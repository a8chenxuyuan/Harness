/** 我的连接接口（W4.1-WEB-02）：渠道绑定管理。 */
import { del, get } from "./http";
import type { ChannelBinding, ChannelBindingList } from "./types";

/** GET /channels/bindings：当前用户全部绑定（脱敏）。 */
export async function fetchBindings(): Promise<ChannelBinding[]> {
  const resp = await get<ChannelBindingList>("/channels/bindings");
  return resp.items;
}

/** DELETE /channels/bindings/{id}：注销一条绑定（幂等）。 */
export async function revokeBinding(bindingId: string): Promise<void> {
  await del(`/channels/bindings/${bindingId}`);
}
