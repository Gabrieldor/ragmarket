"use client";

import { useEffect, useState } from "react";
import {
  CircleNotchIcon,
  MoonIcon,
  PauseIcon,
  PlayIcon,
  WarningIcon,
  WifiSlashIcon,
  type Icon,
} from "@phosphor-icons/react";
import { api, CollectorStatus } from "@/lib/api";

const POLL_MS = 5000;
const TICK_MS = 1000;

function parseLocal(iso: string | null): Date | null {
  if (!iso) return null;
  // Backend timestamps are naive *local* time (datetime.now(), not UTC -- see the
  // convention documented in db/models.py), so parse as-is: no "Z" suffix, which would
  // tell the browser to treat it as UTC and shift it by the local offset on display.
  return new Date(iso);
}

function formatTime(iso: string | null): string {
  const date = parseLocal(iso);
  return date ? date.toLocaleTimeString() : "";
}

function formatCountdown(targetIso: string | null, now: Date): string {
  const target = parseLocal(targetIso);
  if (!target) return "";
  const remainingMs = target.getTime() - now.getTime();
  if (remainingMs <= 0) return "any moment now";

  const totalSeconds = Math.floor(remainingMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export default function CollectorStatusBanner({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<CollectorStatus | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [toggling, setToggling] = useState(false);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      api
        .collectorStatus()
        .then((data) => {
          if (!cancelled) setStatus(data);
        })
        .catch(() => {
          if (!cancelled) {
            setStatus({
              state: "offline", current_item_name: null, next_cycle_at: null,
              consecutive_rate_limits: 0, updated_at: null, paused: false,
            });
          }
        });
    }
    poll();
    const pollInterval = setInterval(poll, POLL_MS);
    const tickInterval = setInterval(() => setNow(new Date()), TICK_MS);
    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      clearInterval(tickInterval);
    };
  }, []);

  if (!status) return null;

  async function togglePause() {
    if (toggling) return;
    setToggling(true);
    try {
      const updated = await (status?.paused ? api.resumeCollector() : api.pauseCollector());
      setStatus(updated);
    } finally {
      setToggling(false);
    }
  }

  async function requestRetry() {
    if (retrying) return;
    setRetrying(true);
    try {
      const updated = await api.retryCollector();
      setStatus(updated);
    } finally {
      setRetrying(false);
    }
  }

  const styles: Record<CollectorStatus["state"], string> = {
    scraping: "bg-blue-50 text-blue-800 border-blue-200",
    sleeping: "bg-muted text-muted-foreground border-border",
    rate_limited: "bg-amber-50 text-amber-800 border-amber-300",
    starting: "bg-muted text-muted-foreground border-border",
    offline: "bg-red-50 text-destructive border-red-300",
    paused: "bg-muted text-muted-foreground border-border",
  };

  const icons: Record<CollectorStatus["state"], Icon> = {
    scraping: CircleNotchIcon,
    sleeping: MoonIcon,
    rate_limited: WarningIcon,
    starting: PlayIcon,
    offline: WifiSlashIcon,
    paused: PauseIcon,
  };
  const StatusIcon = icons[status.state];
  const canToggle = status.state !== "offline";

  const countdown =
    status.state === "sleeping" || status.state === "rate_limited"
      ? formatCountdown(status.next_cycle_at, now)
      : null;

  let message: string;
  switch (status.state) {
    case "scraping":
      message = `Scraping now${status.current_item_name ? `: ${status.current_item_name}` : "..."}`;
      break;
    case "rate_limited":
      message = `Rate-limited by the site -- resuming at ${formatTime(status.next_cycle_at)} (consecutive hit #${status.consecutive_rate_limits})`;
      break;
    case "sleeping":
      message = `Idle -- next cycle at ${formatTime(status.next_cycle_at)}`;
      break;
    case "starting":
      message = "Collector is starting up...";
      break;
    case "paused":
      message = "Paused -- click to resume";
      break;
    case "offline":
    default:
      message = "Collector is not running (no recent heartbeat)";
      break;
  }

  const isRateLimited = status.state === "rate_limited";
  const clickAction = isRateLimited ? requestRetry : canToggle ? togglePause : undefined;
  const clickable = !!clickAction;
  const hoverClass = clickable ? "cursor-pointer hover:opacity-80 active:opacity-60 transition-opacity" : "";
  const hint = isRateLimited
    ? (retrying ? "Requesting retry…" : "Click to retry now")
    : canToggle
    ? (status.paused ? "Click to resume" : "Click to pause")
    : undefined;

  if (compact) {
    return (
      <div
        role={clickable ? "button" : undefined}
        tabIndex={clickable ? 0 : undefined}
        onClick={clickAction}
        onKeyDown={clickable ? (e) => e.key === "Enter" && clickAction() : undefined}
        className={`border rounded px-2 py-2 text-xs flex items-start gap-2 ${styles[status.state]} ${hoverClass}`}
        title={hint ?? message}
        aria-label={hint}
      >
        <StatusIcon size={16} className={status.state === "scraping" ? "animate-spin shrink-0 mt-0.5" : "shrink-0 mt-0.5"} aria-hidden />
        <div className="min-w-0">
          <div className="font-medium capitalize">{status.state.replace("_", " ")}</div>
          {countdown && <div className="text-sm font-semibold tabular-nums">{countdown}</div>}
          <div className="text-[11px] opacity-80">{isRateLimited ? (retrying ? "Requesting retry…" : "Click to retry now") : message}</div>
        </div>
      </div>
    );
  }

  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickAction}
      onKeyDown={clickable ? (e) => e.key === "Enter" && clickAction() : undefined}
      className={`border rounded px-3 py-2 text-sm flex items-center gap-2 ${styles[status.state]} ${hoverClass}`}
      title={hint}
      aria-label={hint}
    >
      <StatusIcon size={18} className={status.state === "scraping" ? "animate-spin" : ""} aria-hidden />
      <span className="font-medium capitalize">{status.state.replace("_", " ")}</span>
      <span>—</span>
      <span>{isRateLimited ? (retrying ? "Requesting retry…" : "Click to retry now") : message}</span>
      {countdown && !retrying && <span className="font-semibold tabular-nums">({countdown})</span>}
    </div>
  );
}
