"use client";

import { useEffect, useRef, useState } from "react";
import { api, TrackedItem } from "@/lib/api";
import Badge from "@/components/Badge";

export default function ItemRegistrationPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [itemName, setItemName] = useState("");
  const [serverName, setServerName] = useState("FREYA");
  const [storeType, setStoreType] = useState("BUY");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards against out-of-order responses: e.g. the mount fetch and a
  // post-submit refresh racing, where an older response could otherwise
  // overwrite the newer one and make a just-added item disappear.
  const requestIdRef = useRef(0);

  function refresh() {
    const requestId = ++requestIdRef.current;
    api
      .listItems()
      .then((data) => {
        if (requestId === requestIdRef.current) setItems(data);
      })
      .catch((err) => setError(String(err)));
  }

  useEffect(refresh, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!itemName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createItem({ item_name: itemName.trim(), server_name: serverName, store_type: storeType });
      setItemName("");
      refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggle(item: TrackedItem) {
    await api.updateItem(item.id, { is_active: !item.is_active });
    refresh();
  }

  async function handleToggleSoldOut(item: TrackedItem) {
    await api.updateItem(item.id, { sold_out_enabled: !item.sold_out_enabled });
    refresh();
  }

  async function handleDelete(item: TrackedItem) {
    const name = item.display_name || item.item_name;
    const confirmed = window.confirm(
      `Permanently delete "${name}" and all of its scraped history?\n\nThis cannot be undone.`
    );
    if (!confirmed) return;
    try {
      await api.deleteItem(item.id);
      refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Item Registration</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Add items for the collector to scrape, and enable/disable tracking per item.
        </p>
      </div>

      <form onSubmit={handleAdd} className="flex gap-3 items-end flex-wrap">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Item name (exact catalog name)</label>
          <input
            value={itemName}
            onChange={(e) => setItemName(e.target.value)}
            placeholder="e.g. Elunium"
            className="border border-border rounded px-3 py-1.5 text-sm w-56"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Server</label>
          <input
            value={serverName}
            onChange={(e) => setServerName(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm w-28"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Store type</label>
          <select
            value={storeType}
            onChange={(e) => setStoreType(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm"
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </div>
        <button
          type="submit"
          disabled={submitting}
          className="bg-primary text-white text-sm px-4 py-1.5 rounded disabled:opacity-50"
        >
          {submitting ? "Adding..." : "Add item"}
        </button>
      </form>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2">Server</th>
              <th className="px-3 py-2">Store type</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Sold-out detection</th>
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
                </td>
                <td className="px-3 py-2">
                  <Badge variant={item.sold_out_enabled ? "info" : "neutral"}>
                    {item.sold_out_enabled ? "enabled" : "disabled"}
                  </Badge>
                </td>
                <td className="px-3 py-2 space-x-3">
                  <button
                    onClick={() => handleToggle(item)}
                    className="text-secondary hover:underline"
                  >
                    {item.is_active ? "Disable" : "Enable"}
                  </button>
                  <button
                    onClick={() => handleToggleSoldOut(item)}
                    className="text-secondary hover:underline"
                  >
                    {item.sold_out_enabled ? "Disable sold-out" : "Enable sold-out"}
                  </button>
                  <button
                    onClick={() => handleDelete(item)}
                    className="text-destructive hover:underline"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
