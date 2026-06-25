"use client";

import { useEffect, useState } from "react";
import { api, Observation, TrackedItem } from "@/lib/api";

const PAGE_SIZE = 50;

export default function ExplorerPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [trackedItemId, setTrackedItemId] = useState<string>("");
  const [sellerName, setSellerName] = useState("");
  const [shopName, setShopName] = useState("");
  const [mapName, setMapName] = useState("");
  const [page, setPage] = useState(0);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listItems().then(setItems).catch((err) => setError(String(err)));
  }, []);

  function runSearch(nextPage = 0) {
    setPage(nextPage);
    api
      .listObservations({
        tracked_item_id: trackedItemId || undefined,
        seller_name: sellerName || undefined,
        shop_name: shopName || undefined,
        map_name: mapName || undefined,
        limit: PAGE_SIZE,
        offset: nextPage * PAGE_SIZE,
      })
      .then(setObservations)
      .catch((err) => setError(String(err)));
  }

  useEffect(() => {
    runSearch(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const itemNameById = new Map(items.map((i) => [i.id, i.display_name || i.item_name]));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Raw Data Explorer</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Search and browse individual scraped listing observations.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          runSearch(0);
        }}
        className="flex gap-3 items-end flex-wrap"
      >
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Item</label>
          <select
            value={trackedItemId}
            onChange={(e) => setTrackedItemId(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm"
          >
            <option value="">All</option>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name || item.item_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Seller</label>
          <input
            value={sellerName}
            onChange={(e) => setSellerName(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm w-36"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Shop</label>
          <input
            value={shopName}
            onChange={(e) => setShopName(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm w-36"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Map</label>
          <input
            value={mapName}
            onChange={(e) => setMapName(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm w-36"
          />
        </div>
        <button type="submit" className="bg-primary text-white text-sm px-4 py-1.5 rounded">
          Search
        </button>
      </form>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Observed at</th>
              <th className="px-3 py-2">Item</th>
              <th className="px-3 py-2">Price</th>
              <th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Seller</th>
              <th className="px-3 py-2">Shop</th>
              <th className="px-3 py-2">Map</th>
              <th className="px-3 py-2">Pos</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((o) => (
              <tr key={o.id} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2 text-muted-foreground">{o.observed_at.replace("T", " ")}</td>
                <td className="px-3 py-2">{itemNameById.get(o.tracked_item_id) ?? o.tracked_item_id}</td>
                <td className="px-3 py-2">{o.price}</td>
                <td className="px-3 py-2">{o.quantity}</td>
                <td className="px-3 py-2">{o.seller_name}</td>
                <td className="px-3 py-2">{o.shop_name}</td>
                <td className="px-3 py-2">{o.map_name}</td>
                <td className="px-3 py-2 text-muted-foreground">
                  {o.x_pos != null ? `${o.x_pos}/${o.y_pos}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex gap-3 items-center text-sm">
        <button
          disabled={page === 0}
          onClick={() => runSearch(page - 1)}
          className="px-3 py-1 border border-border rounded disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-muted-foreground">Page {page + 1}</span>
        <button
          disabled={observations.length < PAGE_SIZE}
          onClick={() => runSearch(page + 1)}
          className="px-3 py-1 border border-border rounded disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
