/**
 * Parse a user-supplied price string, supporting shorthand suffixes.
 * Mirrors notifications/rule_parser.py's `_parse_price_input`:
 *   "25k"    -> 25000
 *   "25kk"   -> 25000000
 *   "1.5k"   -> 1500
 *   "25000"  -> 25000
 * Returns null if the string doesn't match the expected pattern.
 */
export function parsePriceShorthand(input: string): number | null {
  const trimmed = input.trim();
  const match = /^(\d+(?:[.,]\d+)?)\s*(kk|k)?$/i.exec(trimmed);
  if (!match) return null;
  const number = parseFloat(match[1].replace(",", "."));
  if (Number.isNaN(number)) return null;
  const suffix = (match[2] || "").toLowerCase();
  if (suffix === "kk") return number * 1_000_000;
  if (suffix === "k") return number * 1_000;
  return number;
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://127.0.0.1:8000");

export type TrackedItem = {
  id: number;
  item_name: string;
  display_name: string | null;
  site_item_id: number | null;
  server_name: string;
  store_type: string;
  is_active: boolean;
  poll_interval_override: number | null;
  sold_out_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type Observation = {
  id: number;
  tracked_item_id: number;
  observed_at: string;
  ssi: string | null;
  item_id: number | null;
  price: number;
  quantity: number;
  seller_name: string | null;
  shop_name: string | null;
  server_name: string | null;
  store_type: string | null;
  map_name: string | null;
  x_pos: number | null;
  y_pos: number | null;
  location_source: string | null;
  page_num: number | null;
  rank_on_page: number | null;
};

export type HourOfDayStat = {
  hour: number;
  avg_price: number;
  median_price: number;
  min_price: number;
  max_price: number;
  total_quantity: number;
  listing_count: number;
  days_count: number;
};

export type WeekdayStat = {
  weekday: number;
  is_weekend: boolean;
  avg_price: number;
  median_price: number;
  min_price: number;
  max_price: number;
  total_quantity: number;
  listing_count: number;
  days_count: number;
};

export type WeekendComparison = {
  weekday_avg_price: number | null;
  weekend_avg_price: number | null;
  percent_difference: number | null;
};

export type MapStat = {
  map_name: string | null;
  raw_map_names: string[];
  period_start: string;
  period_end: string;
  avg_price: number;
  listing_count: number;
  total_quantity: number;
  stddev_price: number;
  estimated_units_sold: number;
  avg_sale_price: number | null;
  current_quantity: number;       // qty from latest scrape (current stock)
  current_listing_count: number;  // listing count from latest scrape
  today_units_sold: number;       // units sold since midnight
};

export type SalesByHour = {
  hour: number;
  estimated_units_sold: number;
  estimated_revenue: number;
  sale_events: number;
  avg_sale_price: number | null;
};

export type SalesByHourMap = {
  map_name: string;
  hour: number;
  estimated_units_sold: number;
};

export type ListingHistory = {
  ssi: string;
  seller_name: string | null;
  shop_name: string | null;
  map_name: string | null;
  first_observed_at: string;
  last_observed_at: string;
  is_active: boolean;
  initial_quantity: number;
  last_known_quantity: number;
  quantity_sold: number;
};

export type SellerStat = {
  seller_name: string;
  listing_count: number;
  total_quantity: number;
  avg_price: number;
  avg_deviation_from_daily_avg: number;
};

export type Trend = {
  tracked_item_id: number;
  recent_period_days: number;
  recent_avg_price: number | null;
  prior_avg_price: number | null;
  percent_change: number | null;
};

export type CurrentSnapshot = {
  observed_at: string | null;
  listing_count: number;
  total_quantity: number;
  avg_price: number | null;
  median_price: number | null;
  min_price: number | null;
  max_price: number | null;
};

export type CollectorStatus = {
  state: "starting" | "scraping" | "sleeping" | "rate_limited" | "offline" | "paused";
  current_item_name: string | null;
  next_cycle_at: string | null;
  next_item_at: string | null;
  consecutive_rate_limits: number;
  paused: boolean;
  updated_at: string | null;
};

export type ScraperConfig = {
  outlier_factor: number;
  updated_at: string;
};

export type CollectorConfig = {
  poll_interval_seconds: number;
  item_delay_seconds: number;
  location_click_delay_seconds: number;
  updated_at: string;
};

export type OutlierObservation = {
  id: number;
  tracked_item_id: number;
  item_name: string;
  observed_at: string;
  price: number;
  quantity: number;
  seller_name: string | null;
  shop_name: string | null;
  map_name: string | null;
  cycle_median_price: number;
  price_multiple: number;
};

export type SaleEvent = {
  id: number;
  tracked_item_id: number;
  ssi: string;
  seller_name: string | null;
  map_name: string | null;
  quantity_sold: number;
  price: number | null;
  sale_attributed_at: string;
  method: "decrease" | "sellout_no_relist" | "sellout_partial_relist";
  relisted_ssi: string | null;
  relisted_quantity: number | null;
};

export type SaleMethodBreakdown = {
  method: string;
  event_count: number;
  total_quantity_sold: number;
};

export type ThresholdBreakdown = {
  available: { total: number; by_map: { map_name: string; count: number }[] };
  sold: { total: number; by_map: { map_name: string; count: number }[] };
};

export type MapAlias = {
  id: number;
  raw_map_name: string;
  canonical_name: string;
  created_at: string;
};

export type SoldOutConfig = {
  threshold_ratio: number;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  updated_at: string;
};

export type SoldOutEvent = {
  id: number;
  tracked_item_id: number;
  ssi: string;
  seller_name: string | null;
  shop_name: string | null;
  map_name: string | null;
  baseline_quantity: number;
  quantity_at_trigger: number;
  threshold_ratio: number;
  triggered_at: string;
  recorded_at: string;
};

export type SoldOutSummary = {
  tracked_item_id: number;
  active_count: number;
};

export type WatchRule = {
  id: number;
  raw: string;
  item_name: string;
  operator: string;
  target_price: number;
  is_active: boolean;
  state_active: boolean;
  last_price: number | null;
  last_checked_price: number | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
};

export type NotificationEvent = {
  id: number;
  watch_rule_id: number;
  event_type: "triggered" | "cleared" | "price_changed";
  price: number | null;
  old_price: number | null;
  created_at: string;
};

export type NotificationSettings = {
  discord_token_masked: string | null;
  channel_id: string | null;
  user_mention: string;
  local_sound: boolean;
  variance_percent: number;
  min_items_below: number;
  rule_delay_seconds: number;
  store_type: string;
  server_type: string;
  max_pages: number;
  updated_at: string;
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export const api = {
  listItems: (activeOnly = false) =>
    apiFetch<TrackedItem[]>(`/items?active_only=${activeOnly}`),
  createItem: (payload: { item_name: string; display_name?: string; server_name?: string; store_type?: string }) =>
    apiFetch<TrackedItem>("/items", { method: "POST", body: JSON.stringify(payload) }),
  updateItem: (
    id: number,
    payload: { is_active?: boolean; poll_interval_override?: number; sold_out_enabled?: boolean }
  ) => apiFetch<TrackedItem>(`/items/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteItem: (id: number) => apiFetch<void>(`/items/${id}`, { method: "DELETE" }),

  listObservations: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    }
    return apiFetch<Observation[]>(`/observations?${qs.toString()}`);
  },

  hourly: (itemId: number) => apiFetch<HourOfDayStat[]>(`/analytics/${itemId}/hourly`),
  currentSnapshot: (itemId: number) => apiFetch<CurrentSnapshot>(`/analytics/${itemId}/current`),
  weekday: (itemId: number) => apiFetch<WeekdayStat[]>(`/analytics/${itemId}/weekday`),
  weekendVsWeekday: (itemId: number) =>
    apiFetch<WeekendComparison>(`/analytics/${itemId}/weekend-vs-weekday`),
  mapAnalysis: (itemId: number, params: { start?: string; end?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.start) qs.set("start", params.start);
    if (params.end) qs.set("end", params.end);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return apiFetch<MapStat[]>(`/analytics/${itemId}/map${suffix}`);
  },
  salesByHour: (itemId: number) => apiFetch<SalesByHour[]>(`/analytics/${itemId}/sales-by-hour`),
  salesByHourByMap: (itemId: number, params: { start?: string; end?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.start) qs.set("start", params.start);
    if (params.end) qs.set("end", params.end);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return apiFetch<SalesByHourMap[]>(`/analytics/${itemId}/sales-by-hour-map${suffix}`);
  },
  sellers: (itemId: number) => apiFetch<SellerStat[]>(`/analytics/${itemId}/sellers`),
  listingHistory: (itemId: number) => apiFetch<ListingHistory[]>(`/analytics/${itemId}/listing-history`),
  trend: (itemId: number, days = 30) =>
    apiFetch<Trend>(`/analytics/${itemId}/trend?days=${days}`),

  saleEvents: (itemId: number, params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    }
    return apiFetch<SaleEvent[]>(`/analytics/${itemId}/sale-events?${qs.toString()}`);
  },
  saleMethodBreakdown: (itemId: number, params: { start?: string; end?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.start) qs.set("start", params.start);
    if (params.end) qs.set("end", params.end);
    return apiFetch<SaleMethodBreakdown[]>(`/analytics/${itemId}/sale-method-breakdown?${qs.toString()}`);
  },
  thresholdBreakdown: (
    itemId: number,
    params: {
      date: string;
      hour?: number;
      avail_op: "above" | "below";
      avail_price: number;
      sold_op: "above" | "below";
      sold_price: number;
    }
  ) => {
    const qs = new URLSearchParams();
    qs.set("date", params.date);
    if (params.hour !== undefined) qs.set("hour", String(params.hour));
    qs.set("avail_op", params.avail_op);
    qs.set("avail_price", String(params.avail_price));
    qs.set("sold_op", params.sold_op);
    qs.set("sold_price", String(params.sold_price));
    return apiFetch<ThresholdBreakdown>(`/analytics/${itemId}/threshold-breakdown?${qs.toString()}`);
  },

  getScraperConfig: () => apiFetch<ScraperConfig>("/scraper-config"),
  updateScraperConfig: (body: { outlier_factor: number }) =>
    apiFetch<ScraperConfig>("/scraper-config", { method: "PATCH", body: JSON.stringify(body) }),

  getCollectorConfig: () => apiFetch<CollectorConfig>("/collector/config"),
  updateCollectorConfig: (body: Partial<{ poll_interval_seconds: number; item_delay_seconds: number; location_click_delay_seconds: number }>) =>
    apiFetch<CollectorConfig>("/collector/config", { method: "PATCH", body: JSON.stringify(body) }),

  collectorStatus: () => apiFetch<CollectorStatus>("/collector/status"),
  listOutliers: (params?: { item_id?: number; start?: string; end?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.item_id != null) qs.set("item_id", String(params.item_id));
    if (params?.start) qs.set("start", params.start);
    if (params?.end) qs.set("end", params.end);
    if (params?.limit != null) qs.set("limit", String(params.limit));
    if (params?.offset != null) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return apiFetch<OutlierObservation[]>(`/analytics/outliers${q ? `?${q}` : ""}`);
  },
  pauseCollector: () => apiFetch<CollectorStatus>("/collector/pause", { method: "POST" }),
  resumeCollector: () => apiFetch<CollectorStatus>("/collector/resume", { method: "POST" }),
  retryCollector: () => apiFetch<CollectorStatus>("/collector/retry", { method: "POST" }),

  getSoldOutConfig: () => apiFetch<SoldOutConfig>("/sold-out/config"),
  updateSoldOutConfig: (payload: {
    threshold_ratio?: number;
    quiet_hours_start?: string;
    quiet_hours_end?: string;
    clear_quiet_hours?: boolean;
  }) => apiFetch<SoldOutConfig>("/sold-out/config", { method: "PATCH", body: JSON.stringify(payload) }),
  listSoldOutEvents: (tracked_item_id?: number) => {
    const qs = new URLSearchParams();
    if (tracked_item_id !== undefined) qs.set("tracked_item_id", String(tracked_item_id));
    return apiFetch<SoldOutEvent[]>(`/sold-out/events?${qs.toString()}`);
  },
  soldOutSummary: () => apiFetch<SoldOutSummary[]>("/sold-out/summary"),

  listMapAliases: () => apiFetch<MapAlias[]>("/map-aliases"),
  addMapAlias: (canonical_name: string, raw_map_names: string[]) =>
    apiFetch<MapAlias[]>("/map-aliases", {
      method: "POST",
      body: JSON.stringify({ canonical_name, raw_map_names }),
    }),
  deleteMapAlias: (id: number) => apiFetch<void>(`/map-aliases/${id}`, { method: "DELETE" }),

  listWatchRules: (activeOnly = false) =>
    apiFetch<WatchRule[]>(`/watch-rules?active_only=${activeOnly}`),
  addWatchRule: (raw: string) =>
    apiFetch<WatchRule>("/watch-rules", { method: "POST", body: JSON.stringify({ raw }) }),
  updateWatchRule: (id: number, payload: { is_active?: boolean }) =>
    apiFetch<WatchRule>(`/watch-rules/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteWatchRule: (id: number) => apiFetch<void>(`/watch-rules/${id}`, { method: "DELETE" }),

  getNotificationSettings: () => apiFetch<NotificationSettings>("/notifications/settings"),
  updateNotificationSettings: (payload: Partial<{
    discord_token: string;
    channel_id: string;
    user_mention: string;
    local_sound: boolean;
    variance_percent: number;
    min_items_below: number;
    rule_delay_seconds: number;
    store_type: string;
    server_type: string;
    max_pages: number;
  }>) =>
    apiFetch<NotificationSettings>("/notifications/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  rotateIp: () =>
    apiFetch<{ message: string }>("/admin/rotate-ip", { method: "POST" }),

  listNotificationEvents: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    }
    return apiFetch<NotificationEvent[]>(`/notifications/events?${qs.toString()}`);
  },
};

export const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
