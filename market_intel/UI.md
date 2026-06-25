# UI/UX Improvement Plan — Market Intelligence Dashboard

Status: **Phases 0-3 and 5 implemented (2026-06-24); Phase 4 (dark mode) and Phase 6 (shadcn)
skipped by user decision** -- see "Open questions" resolutions below. Built using the
`ui-ux-pro-max` skill (installed this session at
`D:\Rag\.claude\skills\ui-ux-pro-max\`) to ground every recommendation in its style/color/
typography/chart/UX databases rather than ad-hoc taste. Re-run `python
.claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <domain>` from `D:\Rag` any time
a recommendation here needs to be re-checked or extended — domains: `style`, `color`, `chart`,
`product`, `ux`, `typography`, `icons`, `react`, `web`, `google-fonts`; stacks: `nextjs`, `shadcn`,
`react`, etc. Like `cloud.md`, check items off as completed and add notes inline.

## Current state (as of 2026-06-24)

- **9 top-nav links** in one flat row (`layout.tsx`'s `NAV_LINKS`): Overview, Price Watcher, Item
  Registration, Map Analysis, Raw Data Explorer, Listing History, My Sales, Sellout Audit,
  Settings. No grouping — will keep growing and is already cramped.
- **No design tokens at all.** Every page hardcodes raw Tailwind utility classes
  (`bg-gray-900`, `text-blue-600`, `bg-green-50 text-green-700`, etc.) ad hoc, page by page —
  no shared badge/button/card component, so the same concept (e.g. a status badge) is styled
  slightly differently depending on which page wrote it.
- **No icons anywhere.** Every status indicator, nav link, and action is plain text.
- **Light-mode-only, intentionally** (`globals.css` comment: "internal tool"). Worth
  re-confirming this is still the right call now that the app also includes Discord
  notifications and could plausibly run unattended on a server (see `cloud.md`) — a NOC-style
  dark theme is common for exactly this kind of always-on monitoring dashboard.
- **Found while researching this plan**: `globals.css`'s `body { font-family: Arial, Helvetica,
  sans-serif; }` silently overrides the Geist font already being loaded via `next/font` in
  `layout.tsx` — the app has never actually been rendering in the font it thinks it's using. Fix
  this regardless of which typography direction below is chosen.
- **Tables have no horizontal-scroll wrapper.** Every `<table>` across the app (Item Registration,
  Maps, Explorer, Audit, Listing History, Watcher, My Sales) is a bare `<table className="w-full">`
  with no `overflow-x-auto` container — confirmed against the skill's `ux` guidance ("Tables can
  overflow on mobile... Use horizontal scroll or card layout", Severity: Medium) as a real,
  reproducible gap, not a hypothetical one.
- **Charts**: already using Recharts, which the skill rates 9/10 for this product type — no
  library change needed, just styling/accessibility polish (see Phase 3).

## Skill-driven direction

Queried `product`, `style`, `color`, `typography`, `chart`, `ux`, `web`, `react`, and `icons`
against the actual shape of this app (an internal, data-dense, partly-real-time analytics
dashboard for a game economy). Closest matches:

- **Product type**: *Analytics Dashboard* → primary style **Data-Dense Dashboard**, secondary
  **Real-Time Monitoring** (the live `CollectorStatusBanner` polling every 5s is exactly this
  pattern) and **Drill-Down Analytics** (the Sellout Audit / Map Analysis "click row to expand"
  interactions already follow this pattern without it being named).
- **Color palette** (Analytics Dashboard, light mode):

  | Token | Value | Use |
  |---|---|---|
  | `--color-primary` | `#1E40AF` | primary actions, active nav |
  | `--color-secondary` | `#3B82F6` | links, secondary emphasis |
  | `--color-accent` | `#D97706` | highlights (WCAG-adjusted from the skill's default for 3:1) |
  | `--color-background` | `#F8FAFC` | page background |
  | `--color-foreground` | `#1E3A8A` | headings |
  | `--color-card` | `#FFFFFF` | card/table surfaces |
  | `--color-card-foreground` | `#1E3A8A` | text on cards |
  | `--color-muted` | `#E9EEF6` | subtle backgrounds (table header rows, disabled states) |
  | `--color-muted-foreground` | `#64748B` | secondary/help text |
  | `--color-border` | `#DBEAFE` | borders/dividers |
  | `--color-destructive` | `#DC2626` | delete/danger actions |
  | `--color-ring` | `#1E40AF` | focus rings |

  **Open question**: a *Financial Dashboard* dark palette (`#020617` bg, green/red
  positive/negative indicators, same family as price-watcher trigger colors) is the skill's
  alternate match and would suit an always-on monitoring screen better if Phase 4 (dark mode)
  is in scope — ask the user which to commit to before Phase 0, or do both (light default +
  dark variant) since `@theme` in Tailwind v4 supports this cleanly.
- **Typography**: *Dashboard Data* pairing — **Fira Code** (headings/numbers — every page here is
  full of prices, quantities, percentages) + **Fira Sans** (body/labels). Matches the skill's own
  "dashboards, analytics, data visualization, admin panels" target exactly.
- **Charts**: keep Recharts. Apply the skill's *Trend Over Time* accessibility note — differentiate
  multi-series lines/bars by **shape/style, not color alone** (relevant to the per-map
  sales-by-hour stacked bar chart and the hourly/weekday price charts) — currently color-only.
- **Tables**: per `shadcn` stack guidance, use a real `<Table>`/`<TableHeader>`/`<TableBody>`
  semantic structure (already mostly followed) but the missing piece is the
  `overflow-x-auto` wrapper + sticky header + `--table-row-height: 36px` consistency called out
  in the Data-Dense Dashboard style spec.
- **Icons**: none currently exist; skill recommends **Phosphor** as primary (`@phosphor-icons/react`)
  with **Heroicons** as fallback for anything Phosphor lacks. Concrete first use: status icons for
  collector state (scraping/sleeping/rate_limited/offline), sold-out/low-stock badges, watch-rule
  triggered/cleared state, sidebar nav icons.
- **Navigation**: the skill's nav guidance is mobile-tab-bar-specific ("at most 5 primary items,
  move extras to More/Settings") but the underlying principle generalizes directly to our 9-link
  flat top nav — group into a left sidebar with sections instead of growing the top row forever.
- **React/Next.js perf**: current pages already fetch independently per `useEffect` (good, already
  parallel) — no violation found of the skill's "parallelize fetching" guidance. No action needed
  here beyond keeping this pattern as new pages are added.

## Step-by-step plan

### Phase 0 — Design tokens

- [x] Fix the font bug: remove/override `globals.css`'s hardcoded `body { font-family: Arial... }`
      so the actually-configured font (whichever is chosen below) renders.
- [x] Resolve the light/dark open question above. **Resolved: light only**, per user answer.
- [x] Add the Analytics Dashboard color tokens (table above) to `globals.css`'s `@theme inline`
      block as CSS variables (Tailwind v4 CSS-first config, matching the project's existing
      pattern — no `tailwind.config.js` exists, confirmed). Also darkened
      `--color-muted-foreground` from the skill's stock `#64748b` to `#475569` — the original
      only cleared ~4.1:1 against `--color-muted` (used together in nested-table backgrounds),
      short of WCAG AA's 4.5:1; see Phase 5 note.
- [x] Swap Geist for the Fira Code/Fira Sans pairing via `next/font/google` in `layout.tsx`,
      Fira Sans as `--font-sans`, Fira Code as `--font-mono`. **Not done**: the per-cell
      `font-mono tabular-nums` treatment on numeric `<td>`s (prices/quantities) across the ~10
      table-heavy pages — left as a follow-up; `--font-mono` is wired and ready for it.
- [x] Replace ad-hoc badge color classes (`bg-green-50 text-green-700`, `bg-amber-50
      text-amber-700`, `bg-gray-100 text-gray-500`, etc. — currently duplicated across Overview,
      Item Registration, Price Watcher, Sold-out events) with one shared `<Badge>` component
      (`components/Badge.tsx`, variants: success/warning/neutral/danger/info) using the new
      semantic tokens, so "active/healthy" vs. "warning" vs. "neutral" always means the same
      color everywhere.

### Phase 1 — Navigation

- [x] Convert the top nav (`layout.tsx`) to a left sidebar (`components/Sidebar.tsx`),
      `--sidebar-width: 240px` per the Data-Dense Dashboard spec. Collapsible on narrow
      viewports: off-canvas drawer below `md`, hamburger toggle, backdrop click and Escape
      both close it.
- [x] Group the 9 existing links into sections, confirmed as proposed:
  - **Monitoring**: Overview, Price Watcher
  - **Items**: Item Registration, Map Analysis, Listing History, Raw Data Explorer
  - **Sales**: My Sales, Sellout Audit
  - **Config**: Settings
- [x] Add a Phosphor icon per nav item and per section header.
- [x] Keep the `CollectorStatusBanner` visible regardless of which page is active — moved to a
      compact variant (`compact` prop) pinned in the sidebar footer; removed the full banner from
      the Overview page to avoid duplication.

### Phase 2 — Component-level polish

- [x] Add `overflow-x-auto` wrappers around every `<table>` (Overview, Item Registration, Maps
      incl. nested expand-row tables, Explorer, Audit incl. nested tables, Listing History,
      Watcher x2, My Sales x3, Settings, Item Detail x3) — done across all ~18 table instances.
- [x] Standardize table header rows to `--color-muted` background + sticky positioning
      (`sticky top-0`) for the main table in each page (nested expand-row tables left
      non-sticky since they're short and already scoped inside a scrolled ancestor).
- [x] Add hover row highlighting (`hover:bg-muted/50` on light rows, `hover:bg-card/50` on rows
      already sitting on a muted background) on every table.
- [x] Replace text-only status indicators with icon + text: collector state banner now shows a
      per-state Phosphor icon (spinning `CircleNotch` while scraping, `Moon`/`Warning`/`Play`/
      `WifiSlash` otherwise); status/condition/sold-out/enabled badges now use the shared
      `<Badge>` component instead of raw `<span>`s.
- [ ] Standardize row height/padding to the literal `--table-row-height: 36px` / `--card-padding:
      12px` tokens — the tokens are defined in `globals.css` but individual `px-3 py-2` cell
      paddings were not rewritten to consume them; the visual result is already consistent
      (every table already used the same `px-3 py-2` pattern) so this is cosmetic-only debt.

### Phase 3 — Charts

- [x] Differentiate multi-series charts by line style/pattern in addition to color: the item
      detail hourly price chart's avg/min/max lines are now solid / `5 5` dash / `2 3 6 3`
      dash, not just three colors. The per-map sales-by-hour stacked bar stays color-only
      (Recharts has no built-in pattern-fill for bars) but its `<Legend>` is always rendered,
      not hover-only, satisfying the minimum bar of the skill's note.
- [x] Audit existing chart colors against the new token palette: all single/dual-series chart
      fills and strokes across Maps, My Sales, and Item Detail now reference
      `var(--color-primary|secondary|accent|destructive)` instead of ad-hoc hex. The Map
      Analysis per-map categorical palette (`MAP_COLORS`, 10 hues) was intentionally left as
      ad-hoc hex — it needs an arbitrary number of mutually distinct hues for an unbounded set
      of maps, which a 4-color semantic token family can't provide.

### Phase 4 — Dark mode — **skipped**, per user decision (light-only confirmed for this pass)

- [ ] Add the Financial Dashboard dark palette as a second `@theme` variant (Tailwind v4 supports
      `@theme` + a `dark:` variant strategy or a `[data-theme="dark"]` selector cleanly).
- [ ] Add a theme toggle (persisted via `localStorage`, using the skill's "Hydration No Flicker"
      guidance — inline script before hydration, not a `useEffect` that flashes).

### Phase 5 — Accessibility pass

- [x] Ran the new color palette through a contrast check (manual sRGB luminance calc, not just
      the skill's CSV claim): `--color-accent` (#D97706) on `--color-card` (white) is ~3.2:1 —
      fine, since accent is only used for non-text chart fills here, not body text (WCAG
      1.4.11 needs 3:1 for UI components, not 4.5:1). `--color-muted-foreground` on
      `--color-muted` was the one real failure (~4.1:1, under AA's 4.5:1 for normal text,
      and that combination is genuinely used together in nested-table headers) — fixed by
      darkening the token to `#475569` (now ~6.5:1 against `--color-muted`, ~7.6:1 against
      white).
- [x] Confirm focus rings (`--color-ring`) are visible on every interactive element — added a
      global `a/button/input/select/textarea:focus-visible { outline: 2px solid
      var(--color-ring) }` rule in `globals.css` rather than hand-adding it to every refactored
      component.
- [x] Keyboard-nav test the new sidebar — Escape now closes the mobile drawer (was missing,
      added a `keydown` listener); verified via Playwright that the hamburger button opens the
      drawer and the backdrop/close button close it. Tab order follows DOM order (hamburger →
      nav links → footer banner), no custom `tabindex` needed since everything is a native
      `button`/`a`.

### Phase 6 — Optional: adopt shadcn/ui incrementally — **skipped**, per user decision

- [ ] Not a rewrite — evaluate swapping just the `<Table>` and chart-wrapper primitives for
      shadcn's versions (skill confirms both are first-class shadcn components with Recharts
      integration via `<ChartContainer>`), since shadcn's accessibility/theming is already
      WCAG-conscious out of the box and would reduce how much of Phases 2-3 needs to be hand-rolled.

## Open questions — resolved 2026-06-24

1. **Light only.** Dark mode (Phase 4) explicitly deferred, not implemented.
2. **Sidebar grouping used as originally proposed**, no renaming.
3. **Stayed hand-rolled Tailwind** — Phase 6 / shadcn not adopted this pass.
4. **Phosphor primary + Heroicons fallback confirmed** — only Phosphor ended up needed so far
   (`@phosphor-icons/react`); `@heroicons/react` was installed per the decision but no icon from
   it was actually needed yet, so it's an unused dependency until a Phosphor gap shows up.

## Verified

Ran `npm run build` clean (Turbopack, TypeScript, static generation all passed) and smoke-tested
the running app with Playwright screenshots across Overview, Item Registration, Price Watcher,
Map Analysis, and an Item Detail page (charts), plus the mobile-collapsed sidebar (closed and
opened states). No console errors on any page.
