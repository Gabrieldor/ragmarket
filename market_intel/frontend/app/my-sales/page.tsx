"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  api,
  ItemCostBasis,
  MyListingSession,
  MySalesSummary,
  TrackedItem,
  VendorAlias,
} from "@/lib/api";
import Badge from "@/components/Badge";

export default function MySalesPage() {
  const [aliases, setAliases] = useState<VendorAlias[]>([]);
  const [newAlias, setNewAlias] = useState("");
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
  const [costBasis, setCostBasis] = useState<ItemCostBasis | null>(null);
  const [newCost, setNewCost] = useState("");
  const [summary, setSummary] = useState<MySalesSummary | null>(null);
  const [sessions, setSessions] = useState<MyListingSession[]>([]);
  const [showDismissed, setShowDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refreshAliases() {
    api.listVendorAliases().then(setAliases).catch((err) => setError(String(err)));
  }
  function refreshSummary() {
    api.mySalesSummary().then(setSummary).catch((err) => setError(String(err)));
  }
  function refreshSessions(includeDismissed = showDismissed) {
    api
      .myListingSessions({ limit: 100, include_dismissed: includeDismissed })
      .then(setSessions)
      .catch((err) => setError(String(err)));
  }

  async function handleDismiss(id: number) {
    if (!confirm("Remove this entry from your sales log? It's kept for audit purposes and can be restored later.")) return;
    try {
      await api.dismissMyListingSession(id);
      refreshSessions();
      refreshSummary();
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleRestore(id: number) {
    try {
      await api.restoreMyListingSession(id);
      refreshSessions();
      refreshSummary();
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    refreshAliases();
    refreshSummary();
    refreshSessions();
    api.listItems().then((list) => {
      setItems(list);
      if (list.length > 0) setSelectedItemId(list[0].id);
    }).catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (selectedItemId == null) return;
    api.getCostBasis(selectedItemId).then(setCostBasis).catch((err) => setError(String(err)));
  }, [selectedItemId]);

  async function handleAddAlias(e: React.FormEvent) {
    e.preventDefault();
    if (!newAlias.trim()) return;
    try {
      await api.addVendorAlias(newAlias.trim());
      setNewAlias("");
      refreshAliases();
    } catch (err) {
      setError(String(err));
    }
  }

  async function handleRemoveAlias(id: number) {
    await api.deleteVendorAlias(id);
    refreshAliases();
  }

  async function handleSetCost(e: React.FormEvent) {
    e.preventDefault();
    if (selectedItemId == null || !newCost.trim()) return;
    try {
      const updated = await api.setCostBasis(selectedItemId, Number(newCost));
      setCostBasis(updated);
      setNewCost("");
      refreshSummary();
    } catch (err) {
      setError(String(err));
    }
  }

  const statusVariants: Record<string, "info" | "success" | "neutral"> = {
    active: "info",
    sold_out_early: "success",
    expired: "neutral",
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">My Sales</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Register your character names below to log and analyze your own sales, separate from
          the global market data. Multiple names compile into one combined view.
        </p>
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Your vendor names</h2>
        <form onSubmit={handleAddAlias} className="flex gap-3 items-end mb-3">
          <input
            value={newAlias}
            onChange={(e) => setNewAlias(e.target.value)}
            placeholder="e.g. your character name"
            className="border border-border rounded px-3 py-1.5 text-sm w-56"
          />
          <button type="submit" className="bg-primary text-white text-sm px-4 py-1.5 rounded">
            Add name
          </button>
        </form>
        <div className="flex flex-wrap gap-2">
          {aliases.map((a) => (
            <span
              key={a.id}
              className="bg-muted text-sm px-3 py-1 rounded-full flex items-center gap-2"
            >
              {a.alias_name}
              <button
                onClick={() => handleRemoveAlias(a.id)}
                className="text-muted-foreground hover:text-destructive"
              >
                ×
              </button>
            </span>
          ))}
          {aliases.length === 0 && (
            <p className="text-muted-foreground text-sm">No names registered yet -- add one above.</p>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Cost per unit (for profit calc)</h2>
        <form onSubmit={handleSetCost} className="flex gap-3 items-end">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Item</label>
            <select
              value={selectedItemId ?? ""}
              onChange={(e) => setSelectedItemId(Number(e.target.value))}
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
            <label className="block text-xs text-muted-foreground mb-1">
              Current: {costBasis ? costBasis.cost_per_unit : "not set"}
            </label>
            <input
              value={newCost}
              onChange={(e) => setNewCost(e.target.value)}
              placeholder="cost per unit"
              type="number"
              className="border border-border rounded px-3 py-1.5 text-sm w-36"
            />
          </div>
          <button type="submit" className="bg-primary text-white text-sm px-4 py-1.5 rounded">
            Save
          </button>
        </form>
        <p className="text-muted-foreground text-xs mt-1">
          Updating this only affects future sales -- past profit numbers use whatever the cost
          was at the time of each sale.
        </p>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Summary</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <StatCard title="Total quantity sold" value={summary ? String(summary.total_quantity_sold) : "—"} />
          <StatCard title="Total revenue" value={summary ? Math.round(summary.total_revenue).toLocaleString() : "—"} />
          <StatCard
            title="Total profit"
            value={summary?.total_profit != null ? Math.round(summary.total_profit).toLocaleString() : "—"}
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <h3 className="text-xs font-semibold text-muted-foreground mb-2">By item</h3>
            <div className="overflow-x-auto border border-border rounded">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left sticky top-0">
                  <tr>
                    <th className="px-3 py-2">Item</th>
                    <th className="px-3 py-2">Qty</th>
                    <th className="px-3 py-2">Revenue</th>
                    <th className="px-3 py-2">Profit</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.by_item.map((row) => (
                    <tr key={row.tracked_item_id} className="border-t border-border hover:bg-muted/50">
                      <td className="px-3 py-2 font-medium">{row.item_name}</td>
                      <td className="px-3 py-2">{row.quantity_sold}</td>
                      <td className="px-3 py-2">{Math.round(row.revenue).toLocaleString()}</td>
                      <td className="px-3 py-2">{row.profit != null ? Math.round(row.profit).toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <h3 className="text-xs font-semibold text-muted-foreground mb-2">By map (where do I sell)</h3>
            <div className="overflow-x-auto border border-border rounded">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left sticky top-0">
                  <tr>
                    <th className="px-3 py-2">Map</th>
                    <th className="px-3 py-2">Qty</th>
                    <th className="px-3 py-2">Revenue</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.by_map.map((row) => (
                    <tr key={row.map_name} className="border-t border-border hover:bg-muted/50">
                      <td className="px-3 py-2 font-medium">{row.map_name}</td>
                      <td className="px-3 py-2">{row.quantity_sold}</td>
                      <td className="px-3 py-2">{Math.round(row.revenue).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <h3 className="text-xs font-semibold text-muted-foreground mb-2">By hour of day (when do I sell more)</h3>
          <div className="h-56 border border-border rounded p-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={Array.from({ length: 24 }, (_, hour) => ({
                  label: `${hour}:00`,
                  quantity_sold: summary?.by_hour.find((h) => h.hour === hour)?.quantity_sold ?? 0,
                }))}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" fontSize={12} />
                <YAxis fontSize={12} />
                <Tooltip />
                <Bar dataKey="quantity_sold" fill="var(--color-secondary)" name="Qty sold" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-foreground">Sales log</h2>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={showDismissed}
              onChange={(e) => {
                setShowDismissed(e.target.checked);
                refreshSessions(e.target.checked);
              }}
            />
            Show removed entries
          </label>
        </div>
        <div className="overflow-x-auto border border-border rounded">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left sticky top-0">
              <tr>
                <th className="px-3 py-2">Item</th>
                <th className="px-3 py-2">Seller</th>
                <th className="px-3 py-2">Map</th>
                <th className="px-3 py-2">Listed</th>
                <th className="px-3 py-2">Qty sold / initial</th>
                <th className="px-3 py-2">Revenue</th>
                <th className="px-3 py-2">Profit</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id} className={`border-t border-border hover:bg-muted/50 ${s.dismissed ? "opacity-50" : ""}`}>
                  <td className="px-3 py-2 font-medium">{s.item_name}</td>
                  <td className="px-3 py-2">{s.seller_name}</td>
                  <td className="px-3 py-2">{s.map_name}</td>
                  <td className="px-3 py-2 text-muted-foreground">{s.window_start.replace("T", " ")}</td>
                  <td className="px-3 py-2">{s.total_quantity_sold} / {s.initial_quantity}</td>
                  <td className="px-3 py-2">{Math.round(s.revenue).toLocaleString()}</td>
                  <td className="px-3 py-2">{s.profit != null ? Math.round(s.profit).toLocaleString() : "—"}</td>
                  <td className="px-3 py-2">
                    <Badge variant={statusVariants[s.status] || "neutral"}>{s.status.replace("_", " ")}</Badge>
                    {s.dismissed && (
                      <span className="ml-1 inline-block">
                        <Badge variant="danger">removed</Badge>
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {s.dismissed ? (
                      <button
                        onClick={() => handleRestore(s.id)}
                        className="text-secondary hover:underline text-xs"
                      >
                        Restore
                      </button>
                    ) : (
                      <button
                        onClick={() => handleDismiss(s.id)}
                        className="text-muted-foreground hover:text-destructive text-xs"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sessions.length === 0 && (
          <p className="text-muted-foreground text-sm mt-2">
            No listings logged yet -- register a vendor name above and wait for the collector to
            see one of your listings.
          </p>
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
