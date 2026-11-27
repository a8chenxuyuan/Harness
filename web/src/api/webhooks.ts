/** Webhook 管理 API 封装（W4-CHAN-03）。

后端接口见 src/harness/platform/api/controllers/webhooks.py。
事件推送由后端调度器自动完成，这里只管订阅的登记与查看。
*/

import { del, get, post } from "./http";
import type {
  WebhookCreateBody,
  WebhookCreateData,
  WebhookDeliveryListData,
  WebhookListData,
  WebhookTestData,
} from "./types";

/** POST /webhooks —— 登记新订阅；签名密钥只在本次响应出现，请立即保存。 */
export function createWebhook(body: WebhookCreateBody): Promise<WebhookCreateData> {
  return post<WebhookCreateData>("/webhooks", body);
}

/** GET /webhooks —— 列出租户下全部订阅（脱敏）。 */
export function listWebhooks(): Promise<WebhookListData> {
  return get<WebhookListData>("/webhooks");
}

/** DELETE /webhooks/{id} —— 删除订阅及其投递记录。 */
export function deleteWebhook(id: string): Promise<{ deleted: boolean }> {
  return del<{ deleted: boolean }>(`/webhooks/${encodeURIComponent(id)}`);
}

/** GET /webhooks/{id}/deliveries —— 查询投递记录（最新在前）。 */
export function listWebhookDeliveries(
  id: string,
): Promise<WebhookDeliveryListData> {
  return get<WebhookDeliveryListData>(
    `/webhooks/${encodeURIComponent(id)}/deliveries`,
  );
}

/** POST /webhooks/{id}/test —— 发一条测试事件并返回投递结果。 */
export function testWebhook(id: string): Promise<WebhookTestData> {
  return post<WebhookTestData>(`/webhooks/${encodeURIComponent(id)}/test`);
}
