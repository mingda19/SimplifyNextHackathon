// src/lib/domain.ts
//
// Business rules that used to live inline in legacy-app's pages. Kept in one
// place so the UI layer stays presentational and the rules can't drift between
// the pages that show them.

/* -------------------------------- severity -------------------------------- */

export type Severity = "danger" | "warn" | "ok" | "mute";

/** Most severe first. Used to sort collated tags on a category header. */
export const SEVERITY_RANK: Record<Severity, number> = {
  danger: 0,
  warn: 1,
  ok: 2,
  mute: 3,
};

export type Tag = { k: Severity; label: string };

/* ---------------------------------- stock --------------------------------- */

export type StockItem = {
  sku: string;
  name: string;
  category: string | null;
  unit: string;
  on_hand: number;
  reorder_point: number;
  avg_daily_draw: number;
  unit_cost_sgd: number | string | null;
  preferred_vendor_id: string | null;
  dspi_series: string | null;
};

export type StockAlert = { sku: string; type: "EXPIRING_SOON" | "OVERSTOCKED" | string };

/** Keyed by SKU — the shape GET /orders/inbound returns. */
export type InboundMap = Record<string, { qty_inbound: number } | undefined>;

/** Below this many days of cover an item reads "low cover". */
export const LOW_COVER_DAYS = 14;

/** Fallback bucket for items saved without a category. */
export const UNCATEGORISED = "UNCATEGORISED";

export const daysCover = (it: StockItem) =>
  it.avg_daily_draw > 0 ? it.on_hand / it.avg_daily_draw : Infinity;

/**
 * One item's status tags. A category header collates the union of these, so a
 * collapsed category still tells you whether anything inside needs attention.
 *
 * The first three are deliberately exclusive: an out-of-stock item reads "out
 * of stock" only, never also "below reorder".
 */
export function tagsFor(it: StockItem, alerts: StockAlert[], inbound: InboundMap): Tag[] {
  const t: Tag[] = [];
  if (it.on_hand <= 0) t.push({ k: "danger", label: "out of stock" });
  else if (it.on_hand < it.reorder_point) t.push({ k: "danger", label: "below reorder" });
  else if (daysCover(it) < LOW_COVER_DAYS) t.push({ k: "warn", label: "low cover" });

  if (alerts.some((a) => a.sku === it.sku && a.type === "EXPIRING_SOON"))
    t.push({ k: "warn", label: "expiring soon" });
  if (alerts.some((a) => a.sku === it.sku && a.type === "OVERSTOCKED"))
    t.push({ k: "mute", label: "overstocked" });
  if (inbound[it.sku]) t.push({ k: "ok", label: "on the way" });
  return t;
}

/** Value at cost of a set of items. */
export const stockValue = (items: StockItem[]) =>
  items.reduce((s, it) => s + it.on_hand * Number(it.unit_cost_sgd || 0), 0);

/* ------------------------------- agent runs ------------------------------- */

/**
 * Labels intentionally differ from the raw status values — "completed" means
 * the agent looked and found nothing worth doing, which reads badly as
 * "completed" next to a queue of approvals.
 */
export const RUN_STATUS: Record<string, { kind: Severity; label: string }> = {
  running: { kind: "mute", label: "running" },
  committing: { kind: "warn", label: "decision in progress" },
  completed: { kind: "ok", label: "no action needed" },
  pending_approval: { kind: "warn", label: "needs your approval" },
  approved: { kind: "ok", label: "approved" },
  rejected: { kind: "mute", label: "rejected" },
  failed: { kind: "danger", label: "failed" },
};

export const runStatus = (status: string) =>
  RUN_STATUS[status] ?? { kind: "mute" as Severity, label: status };

/** How the charity is funded decides what the agent produces at the end of a run. */
export const CHARITY_TYPES = {
  B: { label: "Budget funded", detail: "purchase orders" },
  A: { label: "Donation fed", detail: "acquisition checklist" },
} as const;

export type CharityType = keyof typeof CHARITY_TYPES;
export const DEFAULT_CHARITY_TYPE: CharityType = "B";

/* --------------------------------- orders --------------------------------- */

export const ORDER_STATUS: Record<string, { kind: Severity; label: string }> = {
  PLACED: { kind: "warn", label: "on the way" },
  FULFILLED: { kind: "ok", label: "received" },
  CANCELLED: { kind: "mute", label: "cancelled" },
};

export const orderStatus = (status: string) =>
  ORDER_STATUS[status] ?? { kind: "mute" as Severity, label: status.toLowerCase() };

export const isOverdue = (expectedAt: string | null | undefined) =>
  !!expectedAt && new Date(expectedAt) < new Date();

/* -------------------------------- feedback -------------------------------- */

/** Urgency is a 1–5 integer from the feedback service. */
export function urgencySeverity(urgency: number): Severity {
  if (urgency >= 4) return "danger";
  if (urgency === 3) return "warn";
  return "mute";
}

/* -------------------------------- currency -------------------------------- */

/**
 * legacy-app mixed toFixed(0), toFixed(2) and raw interpolation across pages.
 * Two helpers instead: whole dollars for headline stats, cents for line items.
 */
export const formatSGD = (n: number | string | null | undefined) =>
  `S$${Number(n ?? 0).toFixed(2)}`;

export const formatSGDWhole = (n: number | string | null | undefined) =>
  `S$${Math.round(Number(n ?? 0)).toLocaleString("en-SG")}`;
