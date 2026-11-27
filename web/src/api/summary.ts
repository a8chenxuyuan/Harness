/** 今日摘要接口（W4.1-CHAN-06）。 */
import { get } from "./http";

export interface SummaryItem {
  platform: string;
  source: string;
  item_type: string;
  title: string;
  summary: string;
  occurred_at: string;
}

export interface TodaySummary {
  date: string;
  counts: Record<string, number>;
  total: number;
  items: SummaryItem[];
}

/** GET /summary/today */
export async function fetchTodaySummary(): Promise<TodaySummary> {
  return get<TodaySummary>("/summary/today");
}
