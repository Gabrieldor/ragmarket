"use client";

import { useEffect, useState } from "react";
import { api, MapAlias, SoldOutConfig } from "@/lib/api";

export default function SettingsPage() {
  const [config, setConfig] = useState<SoldOutConfig | null>(null);
  const [thresholdPercent, setThresholdPercent] = useState("10");
  const [quietStart, setQuietStart] = useState("00:00");
  const [quietEnd, setQuietEnd] = useState("06:00");
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [aliases, setAliases] = useState<MapAlias[]>([]);
  const [canonicalName, setCanonicalName] = useState("");
  const [rawNames, setRawNames] = useState("");
  const [aliasError, setAliasError] = useState<string | null>(null);
  const [aliasSubmitting, setAliasSubmitting] = useState(false);

  function refreshAliases() {
    api.listMapAliases().then(setAliases).catch((err) => setAliasError(String(err)));
  }

  useEffect(() => {
    api
      .getSoldOutConfig()
      .then((c) => {
        setConfig(c);
        setThresholdPercent(String(Math.round(c.threshold_ratio * 100)));
        setQuietHoursEnabled(c.quiet_hours_start != null && c.quiet_hours_end != null);
        if (c.quiet_hours_start) setQuietStart(c.quiet_hours_start);
        if (c.quiet_hours_end) setQuietEnd(c.quiet_hours_end);
      })
      .catch((err) => setError(String(err)));
    refreshAliases();
  }, []);

  async function handleAddAlias(e: React.FormEvent) {
    e.preventDefault();
    const names = rawNames.split(",").map((n) => n.trim()).filter(Boolean);
    if (!canonicalName.trim() || names.length === 0) return;
    setAliasSubmitting(true);
    setAliasError(null);
    try {
      await api.addMapAlias(canonicalName.trim(), names);
      setCanonicalName("");
      setRawNames("");
      refreshAliases();
    } catch (err) {
      setAliasError(String(err));
    } finally {
      setAliasSubmitting(false);
    }
  }

  async function handleDeleteAlias(id: number) {
    try {
      await api.deleteMapAlias(id);
      refreshAliases();
    } catch (err) {
      setAliasError(String(err));
    }
  }

  const aliasesByGroup = aliases.reduce<Record<string, MapAlias[]>>((groups, alias) => {
    (groups[alias.canonical_name] ||= []).push(alias);
    return groups;
  }, {});

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const ratio = Number(thresholdPercent) / 100;
      const updated = await api.updateSoldOutConfig(
        quietHoursEnabled
          ? { threshold_ratio: ratio, quiet_hours_start: quietStart, quiet_hours_end: quietEnd }
          : { threshold_ratio: ratio, clear_quiet_hours: true }
      );
      setConfig(updated);
      setSaved(true);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!config) {
    return error ? <p className="text-destructive">{error}</p> : <p className="text-muted-foreground">Loading...</p>;
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
      </div>

      <section className="max-w-lg">
        <h2 className="text-sm font-semibold text-foreground mb-2">Low-stock detection</h2>
        <p className="text-muted-foreground text-sm mb-3">
          A listing is flagged once its quantity drops to or below this percentage of what
          it was the first time it was seen. Enable/disable detection per item on the Item
          Registration page.
        </p>
        <form onSubmit={handleSave} className="space-y-4 border border-border rounded p-4">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Low-stock threshold (%)</label>
          <input
            type="number"
            min={1}
            max={99}
            value={thresholdPercent}
            onChange={(e) => setThresholdPercent(e.target.value)}
            className="border border-border rounded px-3 py-1.5 text-sm w-24"
          />
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm mb-2">
            <input
              type="checkbox"
              checked={quietHoursEnabled}
              onChange={(e) => setQuietHoursEnabled(e.target.checked)}
            />
            Suppress detection across a quiet-hours gap
          </label>
          <p className="text-muted-foreground text-xs mb-2">
            Only applies when the gap between two scrapes is abnormally long (real downtime,
            e.g. the PC was off overnight) *and* it overlaps this window -- a normal poll-to-poll
            comparison that simply happens to land on the clock during this window (PC left on)
            is never suppressed.
          </p>
          <div className="flex gap-3 items-end">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">From</label>
              <input
                type="time"
                value={quietStart}
                onChange={(e) => setQuietStart(e.target.value)}
                disabled={!quietHoursEnabled}
                className="border border-border rounded px-3 py-1.5 text-sm disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">To</label>
              <input
                type="time"
                value={quietEnd}
                onChange={(e) => setQuietEnd(e.target.value)}
                disabled={!quietHoursEnabled}
                className="border border-border rounded px-3 py-1.5 text-sm disabled:opacity-50"
              />
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="bg-primary text-white text-sm px-4 py-1.5 rounded disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        {saved && <span className="text-green-700 text-sm ml-3">Saved.</span>}
        </form>
        {error && <p className="text-destructive text-sm mt-2">{error}</p>}
      </section>

      <section className="max-w-2xl">
        <h2 className="text-sm font-semibold text-foreground mb-2">Map aliases</h2>
        <p className="text-muted-foreground text-sm mb-3">
          Group map_name values that are actually the same physical location under one
          display name (e.g. abyss_03 and abyss_04 -- both "Abyss"). Applies to the Map
          Analysis page only; raw observations are never rewritten.
        </p>

        <form onSubmit={handleAddAlias} className="flex gap-3 items-end flex-wrap mb-4">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Display name</label>
            <input
              value={canonicalName}
              onChange={(e) => setCanonicalName(e.target.value)}
              placeholder="Abyss"
              className="border border-border rounded px-3 py-1.5 text-sm w-40"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Raw map names (comma-separated)</label>
            <input
              value={rawNames}
              onChange={(e) => setRawNames(e.target.value)}
              placeholder="abyss_03, abyss_04"
              className="border border-border rounded px-3 py-1.5 text-sm w-64"
            />
          </div>
          <button
            type="submit"
            disabled={aliasSubmitting}
            className="bg-primary text-white text-sm px-4 py-1.5 rounded disabled:opacity-50"
          >
            {aliasSubmitting ? "Adding..." : "Add group"}
          </button>
        </form>
        {aliasError && <p className="text-destructive text-sm mb-2">{aliasError}</p>}

        <div className="overflow-x-auto border border-border rounded">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left sticky top-0">
              <tr>
                <th className="px-3 py-2">Display name</th>
                <th className="px-3 py-2">Raw map names</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(aliasesByGroup).map(([canonical, group]) => (
                <tr key={canonical} className="border-t border-border hover:bg-muted/50">
                  <td className="px-3 py-2 font-medium">{canonical}</td>
                  <td className="px-3 py-2 space-x-2">
                    {group.map((a) => (
                      <span key={a.id} className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 rounded text-xs">
                        {a.raw_map_name}
                        <button
                          onClick={() => handleDeleteAlias(a.id)}
                          className="text-destructive hover:underline"
                          title="Remove from group"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </td>
                  <td className="px-3 py-2"></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {aliases.length === 0 && <p className="text-muted-foreground text-sm mt-2">No map aliases yet.</p>}
      </section>
    </div>
  );
}
