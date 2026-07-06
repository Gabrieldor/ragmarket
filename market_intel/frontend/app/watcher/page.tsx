"use client";

import { useEffect, useRef, useState } from "react";
import { api, NotificationEvent, NotificationSettings, WatchRule } from "@/lib/api";
import Badge from "@/components/Badge";
import { fmtTs } from "@/lib/utils";

const EVENT_LABELS: Record<string, string> = {
  triggered: "Triggered",
  cleared: "Cleared",
  price_changed: "Price changed",
};

export default function WatcherPage() {
  const [rules, setRules] = useState<WatchRule[]>([]);
  const [ruleInput, setRuleInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [events, setEvents] = useState<NotificationEvent[]>([]);
  const [eventsError, setEventsError] = useState<string | null>(null);

  function refreshRules() {
    const requestId = ++requestIdRef.current;
    api
      .listWatchRules()
      .then((data) => {
        if (requestId === requestIdRef.current) setRules(data);
      })
      .catch((err) => setRulesError(String(err)));
  }

  function refreshEvents() {
    api.listNotificationEvents({ limit: 100 }).then(setEvents).catch((err) => setEventsError(String(err)));
  }

  useEffect(refreshRules, []);
  useEffect(refreshEvents, []);
  useEffect(() => {
    api
      .getNotificationSettings()
      .then((s) => {
        setSettings(s);
        setForm({
          channel_id: s.channel_id || "",
          user_mention: s.user_mention || "",
          local_sound: String(s.local_sound),
          variance_percent: String(s.variance_percent),
          min_items_below: String(s.min_items_below),
          rule_delay_seconds: String(s.rule_delay_seconds),
          store_type: s.store_type,
          server_type: s.server_type,
          max_pages: String(s.max_pages),
          global_excluded_maps: s.global_excluded_maps || "",
          discord_token: "",
        });
      })
      .catch((err) => setSettingsError(String(err)));
  }, []);

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault();
    if (!ruleInput.trim()) return;
    setSubmitting(true);
    setRulesError(null);
    try {
      await api.addWatchRule(ruleInput.trim());
      setRuleInput("");
      refreshRules();
    } catch (err) {
      setRulesError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggleRule(rule: WatchRule) {
    await api.updateWatchRule(rule.id, { is_active: !rule.is_active });
    refreshRules();
  }

  async function handleDeleteRule(rule: WatchRule) {
    if (!window.confirm(`Delete watch rule "${rule.raw}"? This also removes its history.`)) return;
    try {
      await api.deleteWatchRule(rule.id);
      refreshRules();
      refreshEvents();
    } catch (err) {
      setRulesError(String(err));
    }
  }

  async function handleSaveSettings(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSettingsError(null);
    setSaved(false);
    try {
      const payload: Record<string, unknown> = {
        channel_id: form.channel_id,
        user_mention: form.user_mention,
        local_sound: form.local_sound === "true",
        variance_percent: Number(form.variance_percent),
        min_items_below: Number(form.min_items_below),
        rule_delay_seconds: Number(form.rule_delay_seconds),
        store_type: form.store_type,
        server_type: form.server_type,
        max_pages: Number(form.max_pages),
        global_excluded_maps: (form.global_excluded_maps || "").trim(),
      };
      if (form.discord_token) payload.discord_token = form.discord_token;
      const updated = await api.updateNotificationSettings(payload);
      setSettings(updated);
      setForm((f) => ({ ...f, discord_token: "" }));
      setSaved(true);
    } catch (err) {
      setSettingsError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Price Watcher</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Watch rules for price/supply alerts (e.g. "Elunium &gt; 30000"), checked every
          collector cycle before the market intel scrape. Notifications are sent via Discord
          or a local sound beep, per the settings below. Also supports "+7 Item [1] @map
          !excludedmap #200 &lt; 25kk" style tokens for refine level, slot count,
          required/excluded maps, and minimum quantity.
        </p>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Watch rules</h2>
        <form onSubmit={handleAddRule} className="flex gap-3 items-end flex-wrap mb-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Rule (e.g. "Elunium &gt; 30k" or "Oridecon &lt; 15000")
            </label>
            <input
              value={ruleInput}
              onChange={(e) => setRuleInput(e.target.value)}
              placeholder="Elunium > 30000"
              className="border border-border rounded px-3 py-1.5 text-sm w-72"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="bg-primary text-white text-sm px-4 py-1.5 rounded disabled:opacity-50"
          >
            {submitting ? "Adding..." : "Add rule"}
          </button>
        </form>
        {rulesError && <p className="text-destructive text-sm mb-2">{rulesError}</p>}

        <div className="overflow-x-auto border border-border rounded">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left sticky top-0">
              <tr>
                <th className="px-3 py-2">Rule</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Trigger price</th>
                <th className="px-3 py-2">Current price</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="border-t border-border hover:bg-muted/50">
                  <td className="px-3 py-2 font-medium">{rule.raw}</td>
                  <td className="px-3 py-2">
                    <Badge variant={rule.is_active ? "success" : "neutral"}>
                      {rule.is_active ? "enabled" : "disabled"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={rule.state_active ? "warning" : "neutral"}>
                      {rule.state_active ? "condition active" : "not met"}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {rule.operator} {rule.target_price.toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    {rule.last_checked_price != null ? rule.last_checked_price.toLocaleString() : "—"}
                    {rule.last_checked_at && (
                      <span className="text-muted-foreground text-xs ml-1">
                        (as of {fmtTs(rule.last_checked_at)})
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 space-x-3">
                    <button onClick={() => handleToggleRule(rule)} className="text-secondary hover:underline">
                      {rule.is_active ? "Disable" : "Enable"}
                    </button>
                    <button onClick={() => handleDeleteRule(rule)} className="text-destructive hover:underline">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rules.length === 0 && <p className="text-muted-foreground text-sm mt-2">No watch rules yet.</p>}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Settings</h2>
        {!settings ? (
          <p className="text-muted-foreground text-sm">Loading...</p>
        ) : (
          <form onSubmit={handleSaveSettings} className="space-y-4 border border-border rounded p-4 max-w-xl">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.local_sound === "true"}
                onChange={(e) => setForm((f) => ({ ...f, local_sound: String(e.target.checked) }))}
              />
              Use local sound beeps instead of Discord (no credentials needed)
            </label>

            {form.local_sound !== "true" && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Discord bot token{settings.discord_token_masked ? ` (current: ${settings.discord_token_masked})` : ""}
                  </label>
                  <input
                    type="password"
                    value={form.discord_token || ""}
                    onChange={(e) => setForm((f) => ({ ...f, discord_token: e.target.value }))}
                    placeholder="leave blank to keep current"
                    className="border border-border rounded px-3 py-1.5 text-sm w-full"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Channel ID</label>
                  <input
                    value={form.channel_id || ""}
                    onChange={(e) => setForm((f) => ({ ...f, channel_id: e.target.value }))}
                    className="border border-border rounded px-3 py-1.5 text-sm w-full"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs text-muted-foreground mb-1">User mention (e.g. &lt;@123&gt;)</label>
                  <input
                    value={form.user_mention || ""}
                    onChange={(e) => setForm((f) => ({ ...f, user_mention: e.target.value }))}
                    className="border border-border rounded px-3 py-1.5 text-sm w-full"
                  />
                </div>
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Variance %</label>
                <input
                  type="number"
                  value={form.variance_percent || ""}
                  onChange={(e) => setForm((f) => ({ ...f, variance_percent: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Min items below (0 = off)</label>
                <input
                  type="number"
                  value={form.min_items_below || ""}
                  onChange={(e) => setForm((f) => ({ ...f, min_items_below: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Rule delay (s)</label>
                <input
                  type="number"
                  value={form.rule_delay_seconds || ""}
                  onChange={(e) => setForm((f) => ({ ...f, rule_delay_seconds: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Store type</label>
                <select
                  value={form.store_type || "BUY"}
                  onChange={(e) => setForm((f) => ({ ...f, store_type: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                >
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Server</label>
                <input
                  value={form.server_type || ""}
                  onChange={(e) => setForm((f) => ({ ...f, server_type: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Max pages</label>
                <input
                  type="number"
                  value={form.max_pages || ""}
                  onChange={(e) => setForm((f) => ({ ...f, max_pages: e.target.value }))}
                  className="border border-border rounded px-3 py-1.5 text-sm w-full"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Excluded maps (comma-separated, applies to all rules)
              </label>
              <input
                value={form.global_excluded_maps || ""}
                onChange={(e) => setForm((f) => ({ ...f, global_excluded_maps: e.target.value }))}
                className="border border-border rounded px-3 py-1.5 text-sm w-full"
              />
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
        )}
        {settingsError && <p className="text-destructive text-sm mt-2">{settingsError}</p>}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-foreground mb-2">Notification history</h2>
        <div className="overflow-x-auto border border-border rounded">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left sticky top-0">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Rule</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Price</th>
                <th className="px-3 py-2">Old price</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const rule = rules.find((r) => r.id === e.watch_rule_id);
                return (
                  <tr key={e.id} className="border-t border-border hover:bg-muted/50">
                    <td className="px-3 py-2 text-muted-foreground">{fmtTs(e.created_at)}</td>
                    <td className="px-3 py-2 font-medium">{rule ? rule.raw : `#${e.watch_rule_id}`}</td>
                    <td className="px-3 py-2">{EVENT_LABELS[e.event_type] || e.event_type}</td>
                    <td className="px-3 py-2">{e.price ?? "—"}</td>
                    <td className="px-3 py-2">{e.old_price ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {events.length === 0 && <p className="text-muted-foreground text-sm mt-2">No notifications fired yet.</p>}
        {eventsError && <p className="text-destructive text-sm mt-2">{eventsError}</p>}
      </section>
    </div>
  );
}
