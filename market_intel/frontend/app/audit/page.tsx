"use client";

import { Fragment, useEffect, useState } from "react";
import {
  api,
  SaleEvent,
  SaleMethodBreakdown,
  TrackedItem,
} from "@/lib/api";
import { fmtTs } from "@/lib/utils";

const METHOD_LABELS: Record<string, string> = {
  decrease: "Quantity decrease (reliable)",
  sellout_no_relist: "Sellout, no relist",
  sellout_partial_relist: "Sellout, partial relist",
};

export default function AuditPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [methodBreakdown, setMethodBreakdown] = useState<SaleMethodBreakdown[]>([]);
  const [expandedMethod, setExpandedMethod] = useState<string | null>(null);
  const [methodEvents, setMethodEvents] = useState<SaleEvent[]>([]);
  const [methodLoading, setMethodLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listItems().then((list) => {
      setItems(list);
      if (list.length > 0) setSelectedId(list[0].id);
    }).catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (selectedId == null) return;
    setExpandedMethod(null);
    api
      .saleMethodBreakdown(selectedId, { start: startDate || undefined, end: endDate || undefined })
      .then(setMethodBreakdown)
      .catch((err) => setError(String(err)));
  }, [selectedId, startDate, endDate]);

  async function toggleMethod(method: string) {
    if (expandedMethod === method) {
      setExpandedMethod(null);
      return;
    }
    if (selectedId == null) return;
    setExpandedMethod(method);
    setMethodLoading(true);
    try {
      const events = await api.saleEvents(selectedId, {
        method,
        start: startDate || undefined,
        end: endDate || undefined,
        limit: 200,
      });
      setMethodEvents(events);
    } catch (err) {
      setError(String(err));
    } finally {
      setMethodLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Sellout Audit</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Inspect how much of &quot;estimated units sold&quot; rests on each inference method,
          and drill down to the individual listings behind each classification.
        </p>
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">
          Global market sale-event methods
        </h2>
        <div className="flex gap-4 items-end flex-wrap mb-3">
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
        </div>

        <div className="overflow-x-auto border border-border rounded">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left sticky top-0">
              <tr>
                <th className="px-3 py-2">Method</th>
                <th className="px-3 py-2">Events</th>
                <th className="px-3 py-2">Est. qty sold</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {methodBreakdown.map((m) => (
                <Fragment key={m.method}>
                  <tr className="border-t border-border hover:bg-muted/50">
                    <td className="px-3 py-2 font-medium">{METHOD_LABELS[m.method] || m.method}</td>
                    <td className="px-3 py-2">{m.event_count}</td>
                    <td className="px-3 py-2">{m.total_quantity_sold}</td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => toggleMethod(m.method)}
                        className="text-secondary hover:underline text-xs"
                      >
                        {expandedMethod === m.method ? "Hide events" : "View events"}
                      </button>
                    </td>
                  </tr>
                  {expandedMethod === m.method && (
                    <tr className="border-t border-border bg-muted">
                      <td colSpan={4} className="px-3 py-3">
                        {methodLoading ? (
                          <p className="text-muted-foreground text-sm">Loading...</p>
                        ) : (
                          <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead className="text-left text-muted-foreground">
                                <tr>
                                  <th className="px-2 py-1">Attributed at</th>
                                  <th className="px-2 py-1">Seller</th>
                                  <th className="px-2 py-1">Map</th>
                                  <th className="px-2 py-1">Qty sold</th>
                                  <th className="px-2 py-1">Price</th>
                                  <th className="px-2 py-1">Relisted as</th>
                                </tr>
                              </thead>
                              <tbody>
                                {methodEvents.map((e) => (
                                  <tr key={e.id} className="border-t border-border hover:bg-card/50">
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {fmtTs(e.sale_attributed_at)}
                                    </td>
                                    <td className="px-2 py-1">{e.seller_name}</td>
                                    <td className="px-2 py-1">{e.map_name}</td>
                                    <td className="px-2 py-1 font-medium">{e.quantity_sold}</td>
                                    <td className="px-2 py-1">
                                      {e.price != null ? e.price.toLocaleString() : <span className="text-muted-foreground">—</span>}
                                    </td>
                                    <td className="px-2 py-1 text-muted-foreground">
                                      {e.relisted_ssi ? `qty ${e.relisted_quantity}` : "—"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                        {!methodLoading && methodEvents.length === 0 && (
                          <p className="text-muted-foreground text-sm">No events for this method.</p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {methodBreakdown.length === 0 && (
          <p className="text-muted-foreground text-sm mt-2">No sale events recorded yet for this item.</p>
        )}
      </section>
    </div>
  );
}
