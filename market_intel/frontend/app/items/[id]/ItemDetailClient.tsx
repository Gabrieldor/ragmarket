"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtTs } from "@/lib/utils";
import {
  api,
  CurrentSnapshot,
  HourOfDayStat,
  MapStat,
  SalesByHour,
  SellerStat,
  SoldOutEvent,
  Trend,
  TrackedItem,
  WeekdayStat,
  WeekendComparison,
  WEEKDAY_NAMES,
} from "@/lib/api";

function SalesByHourTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { payload: { estimated_units_sold: number; estimated_revenue: number } }[];
  label?: string;
}) {
  if (!active || !payload || !payload.length) return null;
  const { estimated_units_sold, estimated_revenue } = payload[0].payload;
  return (
    <div className="bg-background border border-border rounded p-2 text-xs shadow">
      <p className="font-semibold mb-1">{label}</p>
      <p>Avg est. units sold: {estimated_units_sold.toFixed(1)}</p>
      <p>Avg est. revenue: {estimated_revenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
    </div>
  );
}

export default function ItemDetailClient({ itemId }: { itemId: number }) {
  const router = useRouter();
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [item, setItem] = useState<TrackedItem | null>(null);
  const [snapshot, setSnapshot] = useState<CurrentSnapshot | null>(null);
  const [hourly, setHourly] = useState<HourOfDayStat[]>([]);
  const [weekday, setWeekday] = useState<WeekdayStat[]>([]);
  const [weekendCmp, setWeekendCmp] = useState<WeekendComparison | null>(null);
  const [sellers, setSellers] = useState<SellerStat[]>([]);
  const [mapStats, setMapStats] = useState<MapStat[]>([]);
  const [salesByHour, setSalesByHour] = useState<SalesByHour[]>([]);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [soldOutEvents, setSoldOutEvents] = useState<SoldOutEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listItems()
      .then((list) => {
        setItems(list);
        setItem(list.find((i) => i.id === itemId) || null);
      })
      .catch((err) => setError(String(err)));
    api.currentSnapshot(itemId).then(setSnapshot).catch((err) => setError(String(err)));
    api.hourly(itemId).then(setHourly).catch((err) => setError(String(err)));
    api.weekday(itemId).then(setWeekday).catch((err) => setError(String(err)));
    api.weekendVsWeekday(itemId).then(setWeekendCmp).catch((err) => setError(String(err)));
    api.sellers(itemId).then(setSellers).catch((err) => setError(String(err)));
    api.mapAnalysis(itemId).then(setMapStats).catch((err) => setError(String(err)));
    api.salesByHour(itemId).then(setSalesByHour).catch((err) => setError(String(err)));
    api.trend(itemId, 30).then(setTrend).catch((err) => setError(String(err)));
    api.listSoldOutEvents(itemId).then(setSoldOutEvents).catch((err) => setError(String(err)));
  }, [itemId]);

  if (error) return <p className="text-destructive">{error}</p>;

  const hourlyChartData = hourly.map((h) => ({ ...h, label: `${h.hour}:00` }));
  const weekdayChartData = weekday.map((w) => ({ ...w, label: WEEKDAY_NAMES[w.weekday] }));
  const salesByHourMap = new Map(salesByHour.map((s) => [s.hour, s]));
  const salesByHourChartData = Array.from({ length: 24 }, (_, hour) => ({
    label: `${hour}:00`,
    estimated_units_sold: salesByHourMap.get(hour)?.estimated_units_sold ?? 0,
    estimated_revenue: salesByHourMap.get(hour)?.estimated_revenue ?? 0,
  }));

  const cheapestHour = hourly.length
    ? hourly.reduce((min, h) => (h.avg_price < min.avg_price ? h : min))
    : null;

  return (
    <div className="space-y-8">
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">
            {item ? item.display_name || item.item_name : `Item #${itemId}`}
          </h1>
          <select
            value={itemId}
            onChange={(e) => router.push(`/items/${e.target.value}`)}
            className="border border-border rounded px-2 py-1 text-sm"
          >
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.display_name || i.item_name}
              </option>
            ))}
          </select>
        </div>
        {item && (
          <p className="text-muted-foreground text-sm mt-1">
            {item.server_name} · {item.store_type} · {item.is_active ? "active" : "paused"}
          </p>
        )}
      </div>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Current market snapshot
          {snapshot?.observed_at && (
            <span className="text-muted-foreground font-normal">
              {" "}
              (as of {fmtTs(snapshot.observed_at)})
            </span>
          )}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard title="Listings" value={snapshot ? String(snapshot.listing_count) : "—"} />
          <StatCard title="Total quantity" value={snapshot ? String(snapshot.total_quantity) : "—"} />
          <StatCard
            title="Avg price"
            value={snapshot?.avg_price != null ? Math.round(snapshot.avg_price).toString() : "—"}
          />
          <StatCard
            title="Median price"
            value={snapshot?.median_price != null ? Math.round(snapshot.median_price).toString() : "—"}
          />
          <StatCard
            title="Min / Max price"
            value={
              snapshot?.min_price != null ? `${snapshot.min_price} / ${snapshot.max_price}` : "—"
            }
          />
        </div>
        {snapshot && snapshot.listing_count === 0 && (
          <p className="text-muted-foreground text-sm mt-2">No observations yet for this item.</p>
        )}
      </section>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard
          title="Cheapest hour (avg)"
          value={cheapestHour ? `${cheapestHour.hour}:00 — ${Math.round(cheapestHour.avg_price)}` : "—"}
        />
        <StatCard
          title="Weekend vs weekday"
          value={
            weekendCmp?.percent_difference != null
              ? `${weekendCmp.percent_difference > 0 ? "+" : ""}${weekendCmp.percent_difference.toFixed(1)}% on weekends`
              : "—"
          }
        />
        <StatCard
          title={`Trend (${trend?.recent_period_days ?? 30}d vs prior)`}
          value={
            trend?.percent_change != null
              ? `${trend.percent_change > 0 ? "+" : ""}${trend.percent_change.toFixed(1)}%`
              : "—"
          }
        />
      </div>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Average price by hour of day</h2>
        <div className="h-64 border border-border rounded p-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={hourlyChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} domain={["auto", "auto"]} />
              <Tooltip />
              <Line type="monotone" dataKey="avg_price" stroke="var(--color-primary)" dot={false} name="Avg price" />
              <Line
                type="monotone"
                dataKey="min_price"
                stroke="var(--color-secondary)"
                strokeDasharray="5 5"
                dot={false}
                name="Min price"
              />
              <Line
                type="monotone"
                dataKey="max_price"
                stroke="var(--color-destructive)"
                strokeDasharray="2 3 6 3"
                dot={false}
                name="Max price"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Avg estimated units sold by hour of day
          <span className="text-muted-foreground font-normal text-xs ml-2">
            (average across all days with sales at that hour — inferred from quantity drops
            and confirmed sellouts)
          </span>
        </h2>
        <div className="h-64 border border-border rounded p-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={salesByHourChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} />
              <Tooltip content={<SalesByHourTooltip />} />
              <Bar dataKey="estimated_units_sold" fill="var(--color-accent)" name="Avg est. units sold" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Average price by weekday</h2>
        <div className="h-64 border border-border rounded p-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={weekdayChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} domain={["auto", "auto"]} />
              <Tooltip />
              <Bar dataKey="avg_price" fill="var(--color-primary)" name="Avg price" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Sellers (sorted by undercutting)</h2>
        <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Seller</th>
              <th className="px-3 py-2">Items (qty)</th>
              <th className="px-3 py-2">Avg price</th>
              <th className="px-3 py-2">Avg deviation from daily market avg</th>
            </tr>
          </thead>
          <tbody>
            {sellers.map((s) => (
              <tr key={s.seller_name} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2 font-medium">{s.seller_name}</td>
                <td className="px-3 py-2">{s.total_quantity}</td>
                <td className="px-3 py-2">{Math.round(s.avg_price)}</td>
                <td
                  className={
                    s.avg_deviation_from_daily_avg < 0 ? "px-3 py-2 text-green-700" : "px-3 py-2 text-foreground"
                  }
                >
                  {s.avg_deviation_from_daily_avg > 0 ? "+" : ""}
                  {Math.round(s.avg_deviation_from_daily_avg)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {sellers.length === 0 && <p className="text-muted-foreground text-sm mt-2">No data yet.</p>}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Price by location
          <Link href="/maps" className="text-secondary hover:underline font-normal text-xs ml-2">
            (full map analysis →)
          </Link>
        </h2>
        <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Map</th>
              <th className="px-3 py-2">Avg price</th>
              <th className="px-3 py-2">Listings</th>
              <th className="px-3 py-2">Qty (now)</th>
              <th className="px-3 py-2">Est. sold (today)</th>
              <th className="px-3 py-2">Avg sale price</th>
            </tr>
          </thead>
          <tbody>
            {mapStats.map((m) => (
              <tr key={m.map_name} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2 font-medium">{m.map_name}</td>
                <td className="px-3 py-2">{Math.round(m.avg_price)}</td>
                <td className="px-3 py-2">{m.current_listing_count}</td>
                <td className="px-3 py-2">{m.current_quantity}</td>
                <td className="px-3 py-2">{m.today_units_sold}</td>
                <td className="px-3 py-2">
                  {m.avg_sale_price != null ? Math.round(m.avg_sale_price).toLocaleString() : <span className="text-muted-foreground">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {mapStats.length === 0 && (
          <p className="text-muted-foreground text-sm mt-2">
            No location data yet -- shop locations are resolved the first time each shop is seen.
          </p>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Low stock listings
          <span className="text-muted-foreground font-normal text-xs ml-2">
            (quantity dropped to or below the configured % of its first-seen quantity --
            configure on the Settings page)
          </span>
        </h2>
        {item && !item.sold_out_enabled ? (
          <p className="text-muted-foreground text-sm">
            Sold-out detection is disabled for this item --{" "}
            <Link href="/items" className="text-secondary hover:underline">
              enable it on the Item Registration page
            </Link>
            .
          </p>
        ) : (
          <>
            <div className="mb-3">
              <StatCard title="Triggered listings" value={String(soldOutEvents.length)} />
            </div>
            <div className="overflow-x-auto border border-border rounded">
            <table className="w-full text-sm">
              <thead className="bg-muted text-left sticky top-0">
                <tr>
                  <th className="px-3 py-2">Triggered at</th>
                  <th className="px-3 py-2">Seller</th>
                  <th className="px-3 py-2">Map</th>
                  <th className="px-3 py-2">Baseline qty</th>
                  <th className="px-3 py-2">Qty at trigger</th>
                </tr>
              </thead>
              <tbody>
                {soldOutEvents.map((e) => (
                  <tr key={e.id} className="border-t border-border hover:bg-muted/50">
                    <td className="px-3 py-2 text-muted-foreground">{fmtTs(e.triggered_at)}</td>
                    <td className="px-3 py-2">{e.seller_name}</td>
                    <td className="px-3 py-2">{e.map_name}</td>
                    <td className="px-3 py-2">{e.baseline_quantity}</td>
                    <td className="px-3 py-2 font-medium">{e.quantity_at_trigger}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            {soldOutEvents.length === 0 && (
              <p className="text-muted-foreground text-sm mt-2">No low-stock listings recorded yet.</p>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function StatCard({ title, value }: { title: string; value: string }) {
  return (
    <div className="border border-border rounded p-4">
      <p className="text-xs text-muted-foreground">{title}</p>
      <p className="text-lg font-semibold mt-1">{value}</p>
    </div>
  );
}
