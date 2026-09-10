import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ItemEditor } from "@/components/stock/item-editor";
import { StockMovement } from "@/components/stock/stock-movement";
import { errorMessage, inventoryClient } from "@/lib/api";
import {
  formatSGDWhole,
  SEVERITY_RANK,
  stockValue,
  tagsFor,
  UNCATEGORISED,
  type InboundMap,
  type Severity,
  type StockAlert,
  type StockItem,
  type Tag,
} from "@/lib/domain";

export const Route = createFileRoute("/(auth)/stock")({
  component: StockPage,
});

const FILTERS = [
  { value: "all", label: "All items" },
  { value: "low", label: "Below reorder point" },
  { value: "expiring", label: "Expiring soon" },
  { value: "inbound", label: "Has stock on the way" },
] as const;

const badgeVariant = (kind: Severity) =>
  kind === "danger" ? "destructive" : kind === "warn" ? "default" : "secondary";

type Group = {
  cat: string;
  items: StockItem[];
  tags: (Tag & { n: number })[];
  value: number;
  needsAttention: boolean;
};

function StatCard({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string | number;
  emphasis?: "danger" | "warn";
}) {
  const tone =
    emphasis === "danger" ? "text-destructive" : emphasis === "warn" ? "text-primary" : "";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`text-3xl tabular-nums ${tone}`}>{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}

function StockPage() {
  const [items, setItems] = useState<StockItem[] | null>(null);
  const [alerts, setAlerts] = useState<StockAlert[]>([]);
  const [inbound, setInbound] = useState<InboundMap>({});
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<string>("all");
  const [openCats, setOpenCats] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<StockItem | "new" | null>(null);
  const [moving, setMoving] = useState<StockItem | null>(null);

  const load = useCallback(async () => {
    const [stock, alertRes, inboundRes] = await Promise.all([
      inventoryClient.GET("/inventory"),
      inventoryClient.GET("/inventory/alerts"),
      inventoryClient.GET("/orders/inbound"),
    ]);

    if (stock.error) {
      toast.error(errorMessage(stock.error, "Could not reach the inventory service."));
      return;
    }
    setItems((Array.isArray(stock.data) ? stock.data : []) as StockItem[]);
    setAlerts((Array.isArray(alertRes.data) ? alertRes.data : []) as StockAlert[]);
    setInbound((inboundRes.data ?? {}) as InboundMap);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo<Group[]>(() => {
    if (!items) return [];
    const term = q.trim().toLowerCase();

    const keep = items.filter((it) => {
      if (term && !`${it.sku} ${it.name} ${it.category}`.toLowerCase().includes(term))
        return false;
      if (only === "low") return it.on_hand < it.reorder_point;
      if (only === "expiring")
        return alerts.some((a) => a.sku === it.sku && a.type === "EXPIRING_SOON");
      if (only === "inbound") return !!inbound[it.sku];
      return true;
    });

    const by: Record<string, StockItem[]> = {};
    for (const it of keep) (by[it.category || UNCATEGORISED] ||= []).push(it);

    return Object.entries(by)
      .map(([cat, list]) => {
        // Collate every distinct tag inside the category, most severe first, so
        // the header carries the same information as opening it would.
        const seen = new Map<string, Tag & { n: number }>();
        for (const it of list)
          for (const t of tagsFor(it, alerts, inbound))
            seen.set(t.label, { ...t, n: (seen.get(t.label)?.n ?? 0) + 1 });
        const tags = [...seen.values()].sort(
          (a, b) => SEVERITY_RANK[a.k] - SEVERITY_RANK[b.k],
        );
        return {
          cat,
          items: [...list].sort((a, b) => a.sku.localeCompare(b.sku)),
          tags,
          value: stockValue(list),
          needsAttention: tags.some((t) => t.k === "danger" || t.k === "warn"),
        };
      })
      .sort(
        (a, b) =>
          Number(b.needsAttention) - Number(a.needsAttention) || a.cat.localeCompare(b.cat),
      );
  }, [items, q, only, alerts, inbound]);

  // Categories needing attention open by default; the rest stay collapsed.
  // Derived rather than seeded into state by an effect, so the default survives
  // a refetch and there is no cascading render on first load.
  const isCatOpen = useCallback(
    (g: Group) => openCats[g.cat] ?? g.needsAttention,
    [openCats],
  );

  const low = (items ?? []).filter((it) => it.on_hand < it.reorder_point).length;
  const expiring = new Set(
    alerts.filter((a) => a.type === "EXPIRING_SOON").map((a) => a.sku),
  ).size;
  const shown = groups.reduce((n, g) => n + g.items.length, 0);
  const allOpen = groups.length > 0 && groups.every(isCatOpen);

  const afterMutation = (message: string) => {
    setEditing(null);
    setMoving(null);
    toast.success(message);
    void load();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Stock</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Grouped by category. A category header carries the tags of everything inside it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="size-3.5" />
            Add item
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items === null ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)
        ) : (
          <>
            <StatCard label="Items tracked" value={items.length} />
            <StatCard
              label="Below reorder point"
              value={low}
              emphasis={low ? "danger" : undefined}
            />
            <StatCard
              label="Expiring soon"
              value={expiring}
              emphasis={expiring ? "warn" : undefined}
            />
            <StatCard label="Stock at cost" value={formatSGDWhole(stockValue(items))} />
          </>
        )}
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <Input
            className="max-w-[260px]"
            placeholder="Search SKU, name or category"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Select value={only} onValueChange={(v) => setOnly(v ?? "all")}>
            <SelectTrigger className="w-[220px]">
              {/* Base UI renders the raw value unless given a mapper. */}
              <SelectValue>
                {(v: string) => FILTERS.find((f) => f.value === v)?.label ?? "All items"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {FILTERS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setOpenCats(Object.fromEntries(groups.map((g) => [g.cat, !allOpen])))
            }
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </Button>
          <span className="text-sm text-muted-foreground">
            {shown} item{shown === 1 ? "" : "s"} in {groups.length}{" "}
            {groups.length === 1 ? "category" : "categories"}
          </span>
        </CardContent>
      </Card>

      {items === null ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : groups.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Nothing matches that filter.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => {
            const isOpen = isCatOpen(g);
            return (
              <Card key={g.cat} className="overflow-hidden py-0">
                <button
                  type="button"
                  onClick={() => setOpenCats((c) => ({ ...c, [g.cat]: !isOpen }))}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
                >
                  {isOpen ? (
                    <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <strong className="min-w-[140px]">{g.cat}</strong>
                  <span className="text-sm text-muted-foreground">
                    {g.items.length} item{g.items.length === 1 ? "" : "s"}
                  </span>
                  <span className="flex flex-1 flex-wrap gap-1.5">
                    {g.tags.map((t) => (
                      <Badge key={t.label} variant={badgeVariant(t.k)}>
                        {t.label}
                        {t.n > 1 ? ` ${t.n}` : ""}
                      </Badge>
                    ))}
                  </span>
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {formatSGDWhole(g.value)}
                  </span>
                </button>

                {isOpen && (
                  <div className="overflow-x-auto border-t">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>SKU</TableHead>
                          <TableHead>Item</TableHead>
                          <TableHead className="text-right">On hand</TableHead>
                          <TableHead className="text-right">Reorder at</TableHead>
                          <TableHead className="text-right">Inbound</TableHead>
                          <TableHead>Tags</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {g.items.map((it) => {
                          const inb = inbound[it.sku];
                          return (
                            <TableRow key={it.sku}>
                              <TableCell className="font-mono text-sm">{it.sku}</TableCell>
                              <TableCell>{it.name}</TableCell>
                              <TableCell className="text-right tabular-nums">
                                {it.on_hand}{" "}
                                <span className="text-xs text-muted-foreground">{it.unit}</span>
                              </TableCell>
                              <TableCell className="text-right tabular-nums text-muted-foreground">
                                {it.reorder_point}
                              </TableCell>
                              <TableCell className="text-right tabular-nums">
                                {inb ? (
                                  <span className="text-primary">+{inb.qty_inbound}</span>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1">
                                  {tagsFor(it, alerts, inbound).map((t) => (
                                    <Badge key={t.label} variant={badgeVariant(t.k)}>
                                      {t.label}
                                    </Badge>
                                  ))}
                                </div>
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex justify-end gap-2">
                                  <Button size="sm" variant="outline" onClick={() => setMoving(it)}>
                                    Move
                                  </Button>
                                  <Button size="sm" variant="outline" onClick={() => setEditing(it)}>
                                    Edit
                                  </Button>
                                </div>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {editing && (
        <ItemEditor
          item={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={afterMutation}
        />
      )}
      {moving && (
        <StockMovement item={moving} onClose={() => setMoving(null)} onSaved={afterMutation} />
      )}
    </div>
  );
}
