"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ActivityIcon,
  BellIcon,
  ChartBarIcon,
  ClipboardTextIcon,
  ClockCounterClockwiseIcon,
  CurrencyCircleDollarIcon,
  CubeIcon,
  GearIcon,
  ListIcon,
  MagnifyingGlassIcon,
  MapTrifoldIcon,
  XIcon,
  type Icon,
} from "@phosphor-icons/react";
import CollectorStatusBanner from "@/components/CollectorStatusBanner";

type NavLink = { href: string; label: string; icon: Icon };
type NavSection = { label: string; icon: Icon; links: NavLink[] };

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Monitoring",
    icon: ActivityIcon,
    links: [
      { href: "/", label: "Overview", icon: ActivityIcon },
      { href: "/watcher", label: "Price Watcher", icon: BellIcon },
    ],
  },
  {
    label: "Items",
    icon: CubeIcon,
    links: [
      { href: "/items", label: "Item Registration", icon: CubeIcon },
      { href: "/maps", label: "Map Analysis", icon: MapTrifoldIcon },
      { href: "/listing-history", label: "Listing History", icon: ClockCounterClockwiseIcon },
      { href: "/explorer", label: "Raw Data Explorer", icon: MagnifyingGlassIcon },
    ],
  },
  {
    label: "Sales",
    icon: ChartBarIcon,
    links: [
      { href: "/my-sales", label: "My Sales", icon: CurrencyCircleDollarIcon },
      { href: "/audit", label: "Sellout Audit", icon: ClipboardTextIcon },
    ],
  },
  {
    label: "Config",
    icon: GearIcon,
    links: [{ href: "/settings", label: "Settings", icon: GearIcon }],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Close the mobile sidebar on every navigation so it doesn't stay pinned open.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open navigation"
        className="md:hidden fixed top-3 left-3 z-30 p-2 rounded border border-border bg-card focus-visible:outline-2 focus-visible:outline-ring"
      >
        <ListIcon size={20} aria-hidden />
      </button>

      {open && (
        <div
          className="md:hidden fixed inset-0 bg-black/30 z-30"
          onClick={() => setOpen(false)}
          aria-hidden
        />
      )}

      <aside
        style={{ width: "var(--sidebar-width)" }}
        className={`shrink-0 border-r border-border bg-card flex flex-col h-screen fixed md:sticky top-0 z-40 transition-transform md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-4 py-4 border-b border-border flex items-center justify-between">
          <span className="font-semibold text-sm text-foreground">Ragnarok Market Intelligence</span>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
            className="md:hidden p-1 -mr-1 rounded focus-visible:outline-2 focus-visible:outline-ring"
          >
            <XIcon size={18} aria-hidden />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4" aria-label="Main navigation">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="flex items-center gap-1.5 px-2 mb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                <section.icon size={14} weight="bold" aria-hidden />
                {section.label}
              </div>
              <div className="space-y-0.5">
                {section.links.map((link) => {
                  const active = pathname === link.href;
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-ring ${
                        active
                          ? "bg-primary/10 text-primary font-medium"
                          : "text-card-foreground hover:bg-muted"
                      }`}
                    >
                      <link.icon size={18} weight={active ? "fill" : "regular"} aria-hidden />
                      {link.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="px-2 py-3 border-t border-border">
          <CollectorStatusBanner compact />
        </div>
      </aside>
    </>
  );
}
