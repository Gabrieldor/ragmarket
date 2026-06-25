"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, TrackedItem } from "@/lib/api";
import Badge from "@/components/Badge";

export default function OverviewPage() {
  const [items, setItems] = useState<TrackedItem[] | null>(null);
  const [soldOutCounts, setSoldOutCounts] = useState<Map<number, number>>(new Map());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listItems().then(setItems).catch((err) => setError(String(err)));
    api
      .soldOutSummary()
      .then((summary) => setSoldOutCounts(new Map(summary.map((s) => [s.tracked_item_id, s.active_count]))))
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return <p className="text-destructive">Failed to load items: {error}</p>;
  }
  if (!items) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  const activeCount = items.filter((i) => i.is_active).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {items.length} tracked item(s), {activeCount} active.
        </p>
      </div>

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2">Server</th>
              <th className="px-3 py-2">Store type</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2 font-medium">{item.display_name || item.item_name}</td>
                <td className="px-3 py-2">{item.server_name}</td>
                <td className="px-3 py-2">{item.store_type}</td>
                <td className="px-3 py-2">
                  <Badge variant={item.is_active ? "success" : "neutral"}>
                    {item.is_active ? "active" : "paused"}
                  </Badge>
                  {(soldOutCounts.get(item.id) ?? 0) > 0 && (
                    <span className="ml-2 inline-block">
                      <Badge variant="warning">Low stock ({soldOutCounts.get(item.id)})</Badge>
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Link href={`/items/${item.id}`} className="text-secondary hover:underline">
                    View detail →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {items.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No tracked items yet.{" "}
          <Link href="/items" className="text-secondary hover:underline">
            Register one here.
          </Link>
        </p>
      )}
    </div>
  );
}
