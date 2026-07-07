"use client";

import { Fragment, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, MapStat, Observation, SalesByHourMap, TrackedItem } from "@/lib/api";

type SortKey = "listing_count" | "median_price" | "current_quantity" | "today_units_sold";

const MAP_COLORS = [
  "#2563eb", "#16a34a", "#dc2626", "#7c3aed", "#ea580c",
  "#0891b2", "#ca8a04", "#db2777", "#4338ca", "#15803d",
];

function mapColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return MAP_COLORS[h % MAP_COLORS.length];
}

export default function MapAnalysisPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mapStats, setMapStats] = useState<MapStat[]>([]);
  const [salesByHourMap, setSalesByHourMap] = useState<SalesByHourMap[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("listing_count");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const [expandedMap, setExpandedMap] = useState<string | null>(null);
  const [expandedRawNames, setExpandedRawNames] = useState<string[]>([]);
  const [expandedListings, setExpandedListings] = useState<Observation[]>([]);
  const [expandedLoading, setExpandedLoading] = useState(false);

  const [excludedMaps, setExcludedMaps] = useState<Set<string>>(new Set());
  const [hideSoldOut, setHideSoldOut] = useState(false);

  useEffect(() => {
    api.listItems().then((list) => {
      setItems(list);
      if (list.length > 0) setSelectedId(list[0].id);
    }).catch((err) => setError(String(err)));
  }, []);

  // Reset the map filter when switching items -- a filter chosen for one item's map list
  // shouldn't silently carry over and hide everything for a different item.
  useEffect(() => {
    setExcludedMaps(new Set());
  }, [selectedId]);

  useEffect(() => {
    if (selectedId == null) return;
    setExpandedMap(null);
    api
      .mapAnalysis(selectedId, { start: startDate || undefined, end: endDate || undefined })
      .then(setMapStats)
      .catch((err) => setError(String(err)));
    api
      .salesByHourByMap(selectedId, { start: startDate || undefined, end: endDate || undefined })
      .then(setSalesByHourMap)
      .catch((err) => setError(String(err)));
  }, [selectedId, startDate, endDate]);

  const allMapNames = Array.from(
    new Set(mapStats.map((m) => m.map_name).filter((n): n is string => Boolean(n)))
  );
  const visibleMapStats = mapStats.filter((m) => m.map_name && !excludedMaps.has(m.map_name));

  const mapNames = Array.from(new Set(salesByHourMap.map((r) => r.map_name))).filter(
    (name) => !excludedMaps.has(name)
  );
  const salesByHourMapChartData = Array.from({ length: 24 }, (_, hour) => {
    const row: Record<string, number | string> = { label: `${hour}:00` };
    for (const name of mapNames) row[name] = 0;
    return row;
  });
  for (const r of salesByHourMap) {
    if (excludedMaps.has(r.map_name)) continue;
    salesByHourMapChartData[r.hour][r.map_name] = r.estimated_units_sold;
  }

  function toggleMapVisibility(name: string) {
    setExcludedMaps((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sortedMapStats = [...visibleMapStats].sort((a, b) => {
    const diff = a[sortKey] - b[sortKey];
    return sortDir === "asc" ? diff : -diff;
  });

  async function fetchExpandedListings(rawNames: string[]) {
    if (selectedId == null) return;
    setExpandedLoading(true);
    try {
      const batches = await Promise.all(
        rawNames.map((rawName) =>
          api.listObservations({
            tracked_item_id: selectedId,
            map_name: rawName,
            limit: 200,
            exclude_sold_out: hideSoldOut,
          })
        )
      );
      const recent = batches.flat();
      // Listings for this item are written with the same observed_at within a cycle, so
      // the most recent batch is just "however many share the newest observed_at" across
      // all the raw names in this group.
      const latestTimestamp = recent.reduce(
        (max, o) => (o.observed_at > max ? o.observed_at : max),
        ""
      );
      setExpandedListings(recent.filter((o) => o.observed_at === latestTimestamp));
    } catch (err) {
      setError(String(err));
    } finally {
      setExpandedLoading(false);
    }
  }

  async function toggleMap(mapStat: MapStat) {
    const mapName = mapStat.map_name;
    if (!mapName) return;
    if (expandedMap === mapName) {
      setExpandedMap(null);
      return;
    }
    if (selectedId == null) return;
    setExpandedMap(mapName);
    // Raw observations are stored under the original (pre-alias) map_name, never the
    // canonical display name shown in this table -- a map-alias group like "Abyss" can
    // span multiple raw names (abyss_03.gat, abyss_04.gat), so query each and merge.
    const rawNames = mapStat.raw_map_names.length > 0 ? mapStat.raw_map_names : [mapName];
    setExpandedRawNames(rawNames);
    await fetchExpandedListings(rawNames);
  }

  // Re-fetch the currently expanded map's listings when the sold-out filter changes.
  useEffect(() => {
    if (expandedMap == null || expandedRawNames.length === 0) return;
    fetchExpandedListings(expandedRawNames);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hideSoldOut]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Map Analysis</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Compare average price by shop location for a tracked item. Click a map row to see its
          individual current listings.
        </p>
      </div>

      <div className="flex gap-4 items-end flex-wrap">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Item</label>
          <select
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(Number(e.target.value))}
            className="border border-border rounded px-3 py-1.5 text-sm"
          >
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name || item.item_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">From</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">To</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm"
          />
        </div>
        {(startDate || endDate) && (
          <button
            onClick={() => {
              setStartDate("");
              setEndDate("");
            }}
            className="text-xs text-secondary hover:underline pb-2"
          >
            Clear dates (all-time)
          </button>
        )}
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground pb-2">
          <input
            type="checkbox"
            checked={hideSoldOut}
            onChange={(e) => setHideSoldOut(e.target.checked)}
          />
          Hide sold out
        </label>
      </div>

      {allMapNames.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Maps shown:</span>
          {allMapNames.map((name) => {
            const visible = !excludedMaps.has(name);
            return (
              <button
                key={name}
                onClick={() => toggleMapVisibility(name)}
                className={
                  visible
                    ? "text-xs px-2 py-1 rounded border border-secondary/30 bg-secondary/10 text-secondary"
                    : "text-xs px-2 py-1 rounded border border-border bg-muted text-muted-foreground line-through"
                }
              >
                {name}
              </button>
            );
          })}
          <button onClick={() => setExcludedMaps(new Set())} className="text-xs text-secondary hover:underline">
            Show all
          </button>
          <button
            onClick={() => setExcludedMaps(new Set(allMapNames))}
            className="text-xs text-secondary hover:underline"
          >
            Hide all
          </button>
        </div>
      )}

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="h-72 border border-border rounded p-2">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={visibleMapStats}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="map_name" fontSize={12} />
            <YAxis fontSize={12} domain={["auto", "auto"]} />
            <Tooltip />
            <Bar dataKey="median_price" fill="var(--color-secondary)" name="Median price" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Avg estimated units sold by hour of day, per map
          <span className="text-muted-foreground font-normal text-xs ml-2">
            (average across days with sales at that hour, broken down by shop location)
          </span>
        </h2>
        <div className="h-72 border border-border rounded p-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={salesByHourMapChartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" fontSize={12} />
              <YAxis fontSize={12} />
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              <Tooltip formatter={(v: any) => (typeof v === "number" ? v.toFixed(1) : v)} />
              <Legend />
              {mapNames.map((name) => (
                <Bar key={name} dataKey={name} stackId="sold" fill={mapColor(name)} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        {mapNames.length === 0 && (
          <p className="text-muted-foreground text-sm mt-2">No sales inferred yet for this item.</p>
        )}
      </div>

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Map</th>
              <SortableHeader label="Median price (± stddev)" sortKey="median_price" current={sortKey} dir={sortDir} onClick={toggleSort} />
              <SortableHeader label="Listings" sortKey="listing_count" current={sortKey} dir={sortDir} onClick={toggleSort} />
              <SortableHeader label="Qty (now)" sortKey="current_quantity" current={sortKey} dir={sortDir} onClick={toggleSort} />
              <SortableHeader label="Est. sold (today)" sortKey="today_units_sold" current={sortKey} dir={sortDir} onClick={toggleSort} />
              <th className="px-3 py-2">Avg sale price</th>
              <th className="px-3 py-2">Period</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {sortedMapStats.map((m) => (
              <Fragment key={m.map_name}>
                <tr className="border-t border-border hover:bg-muted/50">
                  <td className="px-3 py-2 font-medium">{m.map_name}</td>
                  <td className="px-3 py-2">
                    {Math.round(m.median_price)}
                    <span className="text-muted-foreground"> ± {Math.round(m.stddev_price)}</span>
                  </td>
                  <td className="px-3 py-2">{m.current_listing_count}</td>
                  <td className="px-3 py-2">{m.current_quantity}</td>
                  <td className="px-3 py-2">{m.today_units_sold}</td>
                  <td className="px-3 py-2">
                    {m.median_sale_price != null ? Math.round(m.median_sale_price).toLocaleString() : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {m.period_start} → {m.period_end}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => toggleMap(m)}
                      className="text-secondary hover:underline text-xs"
                    >
                      {expandedMap === m.map_name ? "Hide listings" : "View listings"}
                    </button>
                  </td>
                </tr>
                {expandedMap === m.map_name && (
                  <tr className="border-t border-border bg-muted">
                    <td colSpan={7} className="px-3 py-3">
                      {expandedLoading ? (
                        <p className="text-muted-foreground text-sm">Loading...</p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead className="text-left text-muted-foreground">
                              <tr>
                                <th className="px-2 py-1">Price</th>
                                <th className="px-2 py-1">Qty</th>
                                <th className="px-2 py-1">Seller</th>
                                <th className="px-2 py-1">Shop</th>
                              </tr>
                            </thead>
                            <tbody>
                              {expandedListings
                                .sort((a, b) => a.price - b.price)
                                .map((o) => (
                                  <tr key={o.id} className="border-t border-border hover:bg-card/50">
                                    <td className="px-2 py-1 font-medium">{o.price}</td>
                                    <td className="px-2 py-1">{o.quantity}</td>
                                    <td className="px-2 py-1">{o.seller_name}</td>
                                    <td className="px-2 py-1">{o.shop_name}</td>
                                  </tr>
                                ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                      {!expandedLoading && expandedListings.length === 0 && (
                        <p className="text-muted-foreground text-sm">No current listings found.</p>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {mapStats.length === 0 && <p className="text-muted-foreground text-sm">No map data yet.</p>}
      {mapStats.length > 0 && visibleMapStats.length === 0 && (
        <p className="text-muted-foreground text-sm">All maps are hidden -- click "Show all" above.</p>
      )}
    </div>
  );
}

function SortableHeader({
  label,
  sortKey,
  current,
  dir,
  onClick,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: "asc" | "desc";
  onClick: (key: SortKey) => void;
}) {
  const active = current === sortKey;
  return (
    <th
      className="px-3 py-2 cursor-pointer select-none hover:text-foreground"
      onClick={() => onClick(sortKey)}
    >
      {label}
      {active && <span className="text-muted-foreground"> {dir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );
}
