/** 可观测接口：HTTP 指标摘要（owner / admin）。 */
import { get } from "./http";
import type { MetricsSummary } from "./types";

/** GET /observability/metrics */
export async function fetchMetricsSummary(): Promise<MetricsSummary> {
  return get<MetricsSummary>("/observability/metrics");
}
