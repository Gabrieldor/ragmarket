"use client";

import { useEffect, useState } from "react";
import {
  CircleNotchIcon,
  MoonIcon,
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
              consecutive_rate_limits: 0, updated_at: null,
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

  const styles: Record<CollectorStatus["state"], string> = {
    scraping: "bg-blue-50 text-blue-800 border-blue-200",
    sleeping: "bg-muted text-muted-foreground border-border",
    rate_limited: "bg-amber-50 text-amber-800 border-amber-300",
    starting: "bg-muted text-muted-foreground border-border",
    offline: "bg-red-50 text-destructive border-red-300",
  };

  const icons: Record<CollectorStatus["state"], Icon> = {
    scraping: CircleNotchIcon,
    sleeping: MoonIcon,
    rate_limited: WarningIcon,
    starting: PlayIcon,
    offline: WifiSlashIcon,
  };
  const StatusIcon = icons[status.state];

  let message: string;
  switch (status.state) {
    case "scraping":
      message = `Scraping now${status.current_item_name ? `: ${status.current_item_name}` : "..."}`;
      break;
    case "rate_limited":
      message = `Rate-limited by the site -- resuming in ${formatCountdown(status.next_cycle_at, now)} (at ${formatTime(status.next_cycle_at)}, consecutive hit #${status.consecutive_rate_limits})`;
      break;
    case "sleeping":
      message = `Idle -- next cycle in ${formatCountdown(status.next_cycle_at, now)} (at ${formatTime(status.next_cycle_at)})`;
      break;
    case "starting":
      message = "Collector is starting up...";
      break;
    case "offline":
    default:
      message = "Collector is not running (no recent heartbeat)";
      break;
  }

  if (compact) {
    return (
      <div
        className={`border rounded px-2 py-2 text-xs flex items-start gap-2 ${styles[status.state]}`}
        title={message}
      >
        <StatusIcon size={16} className={status.state === "scraping" ? "animate-spin shrink-0 mt-0.5" : "shrink-0 mt-0.5"} aria-hidden />
        <div className="min-w-0">
          <div className="font-medium capitalize">{status.state.replace("_", " ")}</div>
          <div className="text-[11px] opacity-80 line-clamp-2">{message}</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`border rounded px-3 py-2 text-sm flex items-center gap-2 ${styles[status.state]}`}>
      <StatusIcon size={18} className={status.state === "scraping" ? "animate-spin" : ""} aria-hidden />
      <span className="font-medium capitalize">{status.state.replace("_", " ")}</span>
      <span>—</span>
      <span>{message}</span>
    </div>
  );
}
