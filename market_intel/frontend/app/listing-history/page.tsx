"use client";

import { useEffect, useState } from "react";
import { api, ListingHistory, TrackedItem } from "@/lib/api";
import Badge from "@/components/Badge";
import { fmtTs } from "@/lib/utils";

function formatDuration(startIso: string, endIso: string): string {
  const s = startIso.endsWith("Z") ? startIso : startIso + "Z";
  const e = endIso.endsWith("Z") ? endIso : endIso + "Z";
  const ms = new Date(e).getTime() - new Date(s).getTime();
  const totalMinutes = Math.max(0, Math.round(ms / 60000));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export default function ListingHistoryPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rows, setRows] = useState<ListingHistory[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listItems()
      .then((list) => {
        setItems(list);
        if (list.length > 0) setSelectedId(list[0].id);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (selectedId == null) return;
    api.listingHistory(selectedId).then(setRows).catch((err) => setError(String(err)));
  }, [selectedId]);

  const now = new Date().toISOString();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Listing History</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Every distinct listing this item has ever had: how long it stayed up and how much
          it sold (estimated from quantity decreases and confirmed sellouts -- see the
          Sellout Audit page for the inference method's caveats).
        </p>
      </div>

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

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Seller</th>
              <th className="px-3 py-2">Map</th>
              <th className="px-3 py-2">First seen</th>
              <th className="px-3 py-2">Last seen</th>
              <th className="px-3 py-2">Duration</th>
              <th className="px-3 py-2">Initial qty</th>
              <th className="px-3 py-2">Last known qty</th>
              <th className="px-3 py-2">Est. qty sold</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ssi} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2">
                  <Badge variant={row.is_active ? "success" : "neutral"}>
                    {row.is_active ? "active" : "gone"}
                  </Badge>
                </td>
                <td className="px-3 py-2 font-medium">{row.seller_name}</td>
                <td className="px-3 py-2">{row.map_name}</td>
                <td className="px-3 py-2 text-muted-foreground">{fmtTs(row.first_observed_at)}</td>
                <td className="px-3 py-2 text-muted-foreground">{fmtTs(row.last_observed_at)}</td>
                <td className="px-3 py-2">
                  {formatDuration(row.first_observed_at, row.is_active ? now : row.last_observed_at)}
                  {row.is_active ? " (ongoing)" : ""}
                </td>
                <td className="px-3 py-2">{row.initial_quantity}</td>
                <td className="px-3 py-2">{row.last_known_quantity}</td>
                <td className="px-3 py-2 font-medium">{row.quantity_sold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="text-muted-foreground text-sm">No listings recorded yet.</p>}
    </div>
  );
}
