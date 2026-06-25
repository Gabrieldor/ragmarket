"use client";

import { useEffect, useState } from "react";
import { api, OutlierObservation, TrackedItem } from "@/lib/api";

const PAGE_SIZE = 50;

function fmt(n: number) {
  return n.toLocaleString("pt-BR");
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString();
}

export default function OutliersPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [filterItemId, setFilterItemId] = useState<string>("");
  const [outliers, setOutliers] = useState<OutlierObservation[]>([]);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listItems().then(setItems).catch((e) => setError(String(e)));
  }, []);

  function load(nextPage = 0) {
    setLoading(true);
    setError(null);
    api
      .listOutliers({
        item_id: filterItemId ? Number(filterItemId) : undefined,
        limit: PAGE_SIZE,
        offset: nextPage * PAGE_SIZE,
      })
      .then((rows) => {
        setOutliers(rows);
        setPage(nextPage);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Outlier Listings</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Listings priced more than 5× the cycle median. Stored but excluded from all price stats
          and rollups.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          load(0);
        }}
        className="flex gap-3 items-end flex-wrap"
      >
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Item</label>
          <select
            value={filterItemId}
            onChange={(e) => setFilterItemId(e.target.value)}
            className="border rounded px-2 py-1.5 text-sm bg-background"
          >
            <option value="">All items</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.display_name || i.item_name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          className="px-3 py-1.5 rounded text-sm bg-primary text-primary-foreground hover:opacity-90"
        >
          Filter
        </button>
      </form>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : outliers.length === 0 ? (
        <p className="text-muted-foreground text-sm">No outliers found.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-muted-foreground text-xs uppercase">
              <tr>
                <th className="px-3 py-2 text-left">Item</th>
                <th className="px-3 py-2 text-left">Observed at</th>
                <th className="px-3 py-2 text-right">Price</th>
                <th className="px-3 py-2 text-right">Cycle median</th>
                <th className="px-3 py-2 text-right">Multiple</th>
                <th className="px-3 py-2 text-right">Qty</th>
                <th className="px-3 py-2 text-left">Seller</th>
                <th className="px-3 py-2 text-left">Shop</th>
                <th className="px-3 py-2 text-left">Map</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {outliers.map((row) => (
                <tr key={row.id} className="hover:bg-muted/40 transition-colors">
                  <td className="px-3 py-2 font-medium">{row.item_name}</td>
                  <td className="px-3 py-2 text-muted-foreground tabular-nums">
                    {formatTime(row.observed_at)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-amber-700 font-semibold">
                    {fmt(row.price)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                    {fmt(row.cycle_median_price)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <span className="bg-amber-100 text-amber-800 rounded px-1.5 py-0.5 text-xs font-semibold">
                      {row.price_multiple}×
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(row.quantity)}</td>
                  <td className="px-3 py-2 text-muted-foreground">{row.seller_name ?? "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{row.shop_name ?? "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{row.map_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(page > 0 || outliers.length === PAGE_SIZE) && (
        <div className="flex gap-2">
          <button
            onClick={() => load(page - 1)}
            disabled={page === 0}
            className="px-3 py-1 text-sm rounded border border-border disabled:opacity-40"
          >
            ← Prev
          </button>
          <button
            onClick={() => load(page + 1)}
            disabled={outliers.length < PAGE_SIZE}
            className="px-3 py-1 text-sm rounded border border-border disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
