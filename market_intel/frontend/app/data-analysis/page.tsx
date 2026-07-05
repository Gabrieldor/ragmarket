"use client";

import { useEffect, useState } from "react";
import { api, parsePriceShorthand, ThresholdBreakdown, TrackedItem } from "@/lib/api";

function todayDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function DataAnalysisPage() {
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [date, setDate] = useState(todayDate());
  const [hour, setHour] = useState<string>("");

  const [availOp, setAvailOp] = useState<"above" | "below">("above");
  const [availPrice, setAvailPrice] = useState("");
  const [soldOp, setSoldOp] = useState<"above" | "below">("above");
  const [soldPrice, setSoldPrice] = useState("");

  const [result, setResult] = useState<ThresholdBreakdown | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [availPriceError, setAvailPriceError] = useState<string | null>(null);
  const [soldPriceError, setSoldPriceError] = useState<string | null>(null);

  useEffect(() => {
    api.listItems().then((list) => {
      setItems(list);
      if (list.length > 0) setSelectedId(list[0].id);
    }).catch((err) => setError(String(err)));
  }, []);

  async function handleRun(e: React.FormEvent) {
    e.preventDefault();
    if (selectedId == null) return;
    setError(null);
    setAvailPriceError(null);
    setSoldPriceError(null);

    const parsedAvailPrice = parsePriceShorthand(availPrice);
    const parsedSoldPrice = parsePriceShorthand(soldPrice);
    let hasError = false;
    if (parsedAvailPrice == null) {
      setAvailPriceError("Invalid price (e.g. 200k, 1.5k, 200000)");
      hasError = true;
    }
    if (parsedSoldPrice == null) {
      setSoldPriceError("Invalid price (e.g. 200k, 1.5k, 200000)");
      hasError = true;
    }
    if (hasError) return;

    setLoading(true);
    try {
      const data = await api.thresholdBreakdown(selectedId, {
        date,
        hour: hour === "" ? undefined : Number(hour),
        avail_op: availOp,
        avail_price: parsedAvailPrice as number,
        sold_op: soldOp,
        sold_price: parsedSoldPrice as number,
      });
      setResult(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Data Analysis</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Break down how many listings are available or sold above/below a price threshold, per
          map, for a given date (and optionally hour).
        </p>
      </div>

      <form onSubmit={handleRun} className="space-y-4">
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
            <label className="block text-xs text-muted-foreground mb-1">Date</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="border border-border rounded px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Hour</label>
            <select
              value={hour}
              onChange={(e) => setHour(e.target.value)}
              className="border border-border rounded px-3 py-1.5 text-sm"
            >
              <option value="">All day</option>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {h}:00
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex gap-6 flex-wrap">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Available (qty listed)</label>
            <div className="flex gap-2 items-center">
              <div className="flex border border-border rounded overflow-hidden">
                <button
                  type="button"
                  onClick={() => setAvailOp("above")}
                  className={`text-xs px-3 py-1.5 ${
                    availOp === "above" ? "bg-primary text-white" : "bg-card text-card-foreground"
                  }`}
                >
                  Above
                </button>
                <button
                  type="button"
                  onClick={() => setAvailOp("below")}
                  className={`text-xs px-3 py-1.5 ${
                    availOp === "below" ? "bg-primary text-white" : "bg-card text-card-foreground"
                  }`}
                >
                  Below
                </button>
              </div>
              <input
                type="text"
                value={availPrice}
                onChange={(e) => {
                  setAvailPrice(e.target.value);
                  if (availPriceError) setAvailPriceError(null);
                }}
                placeholder="e.g. 200k"
                className="border border-border rounded px-3 py-1.5 text-sm w-32"
              />
            </div>
            {availPriceError && <p className="text-destructive text-xs mt-1">{availPriceError}</p>}
          </div>

          <div>
            <label className="block text-xs text-muted-foreground mb-1">Sold</label>
            <div className="flex gap-2 items-center">
              <div className="flex border border-border rounded overflow-hidden">
                <button
                  type="button"
                  onClick={() => setSoldOp("above")}
                  className={`text-xs px-3 py-1.5 ${
                    soldOp === "above" ? "bg-primary text-white" : "bg-card text-card-foreground"
                  }`}
                >
                  Above
                </button>
                <button
                  type="button"
                  onClick={() => setSoldOp("below")}
                  className={`text-xs px-3 py-1.5 ${
                    soldOp === "below" ? "bg-primary text-white" : "bg-card text-card-foreground"
                  }`}
                >
                  Below
                </button>
              </div>
              <input
                type="text"
                value={soldPrice}
                onChange={(e) => {
                  setSoldPrice(e.target.value);
                  if (soldPriceError) setSoldPriceError(null);
                }}
                placeholder="e.g. 200k"
                className="border border-border rounded px-3 py-1.5 text-sm w-32"
              />
            </div>
            {soldPriceError && <p className="text-destructive text-xs mt-1">{soldPriceError}</p>}
          </div>
        </div>

        <button
          type="submit"
          disabled={selectedId == null || loading}
          className="bg-primary text-white text-sm px-4 py-1.5 rounded disabled:opacity-50"
        >
          {loading ? "Running..." : "Run"}
        </button>
      </form>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {result && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ResultTable title="Available" total={result.available.total} byMap={result.available.by_map} />
          <ResultTable title="Sold" total={result.sold.total} byMap={result.sold.by_map} />
        </div>
      )}
    </div>
  );
}

function ResultTable({
  title,
  total,
  byMap,
}: {
  title: string;
  total: number;
  byMap: { map_name: string; count: number }[];
}) {
  return (
    <section>
      <h2 className="text-sm font-semibold text-foreground mb-2">
        {title}
        <span className="text-muted-foreground font-normal text-xs ml-2">total: {total}</span>
      </h2>
      <div className="overflow-x-auto border border-border rounded">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left sticky top-0">
            <tr>
              <th className="px-3 py-2">Map</th>
              <th className="px-3 py-2">Count</th>
            </tr>
          </thead>
          <tbody>
            {byMap.map((row) => (
              <tr key={row.map_name} className="border-t border-border hover:bg-muted/50">
                <td className="px-3 py-2 font-medium">{row.map_name}</td>
                <td className="px-3 py-2">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {byMap.length === 0 && <p className="text-muted-foreground text-sm mt-2">No results.</p>}
    </section>
  );
}
