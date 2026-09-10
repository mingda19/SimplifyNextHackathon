// Receiving is a per-ORDER confirmation, not a per-item stock edit. The charity
// already told the agent what to buy; when the pallet turns up they tick it off
// rather than re-keying quantities one SKU at a time through stock movements.
import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { errorMessage, inventoryClient } from "@/lib/api";
import { formatSGD, formatSGDWhole, isOverdue, orderStatus, type Severity } from "@/lib/domain";

export const Route = createFileRoute("/(auth)/orders")({
  component: OrdersPage,
});

type Order = {
  order_id: string;
  vendor_id: string;
  sku: string;
  qty: number;
  status: string;
  unit_price_sgd: number;
  total_sgd: number;
  placed_at: string | null;
  expected_at: string | null;
};

const TABS = [
  { value: "PLACED", label: "Open" },
  { value: "FULFILLED", label: "Received" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "ALL", label: "All" },
] as const;

const badgeVariant = (kind: Severity) =>
  kind === "danger" ? "destructive" : kind === "warn" ? "default" : "secondary";

function StatCard({ label, value, emphasis }: { label: string; value: string | number; emphasis?: boolean }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`text-3xl tabular-nums ${emphasis ? "text-primary" : ""}`}>
          {value}
        </CardTitle>
      </CardHeader>
    </Card>
  );
}

function OrdersPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [tab, setTab] = useState<string>("PLACED");
  const [receiving, setReceiving] = useState<Order | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data, error } = await inventoryClient.GET("/orders");
    if (error) {
      toast.error(errorMessage(error, "Could not reach the inventory service."));
      return;
    }
    setOrders((Array.isArray(data) ? data : []) as Order[]);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = useMemo(
    () => (orders ?? []).filter((o) => tab === "ALL" || o.status === tab),
    [orders, tab],
  );

  const open = (orders ?? []).filter((o) => o.status === "PLACED");
  const openValue = open.reduce((t, o) => t + (o.total_sgd || 0), 0);
  const overdue = open.filter((o) => isOverdue(o.expected_at));
  const received = (orders ?? []).filter((o) => o.status === "FULFILLED").length;

  /**
   * Deliberately sequential rather than Promise.all: each receive books stock
   * and the inventory service is the single writer. Failures are tallied, not
   * thrown, so one bad order doesn't abandon the rest of the pallet.
   */
  const receiveAll = async () => {
    setBusy(true);
    let ok = 0;
    let failed = 0;
    for (const o of open) {
      const { error } = await inventoryClient.POST("/orders/{order_id}/receive", {
        params: { path: { order_id: o.order_id } },
        body: {},
      });
      if (error) failed++;
      else ok++;
    }
    setBusy(false);
    setConfirmAll(false);
    toast[failed ? "warning" : "success"](
      `Received ${ok} order${ok === 1 ? "" : "s"}${failed ? `, ${failed} failed` : ""}.`,
    );
    await load();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Incoming orders</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Stock that is paid for but not yet on the shelf. While an order is open its SKU
            is not re-flagged as low, so the agent will not re-order it.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="size-3.5" />
            Refresh
          </Button>
          {open.length > 0 && (
            <Button size="sm" onClick={() => setConfirmAll(true)} disabled={busy}>
              {busy ? "Receiving…" : `Receive all ${open.length}`}
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {orders === null ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)
        ) : (
          <>
            <StatCard label="Open orders" value={open.length} />
            <StatCard label="Value in transit" value={formatSGDWhole(openValue)} />
            <StatCard
              label="Past expected date"
              value={overdue.length}
              emphasis={overdue.length > 0}
            />
            <StatCard label="Received" value={received} />
          </>
        )}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
              {t.value === "PLACED" && open.length > 0 ? ` (${open.length})` : ""}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Vendor</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Value</TableHead>
                <TableHead>Expected</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders === null ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    Loading…
                  </TableCell>
                </TableRow>
              ) : shown.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    {tab === "PLACED" ? "Nothing on the way right now." : "Nothing here."}
                  </TableCell>
                </TableRow>
              ) : (
                shown.map((o) => {
                  const late = isOverdue(o.expected_at) && o.status === "PLACED";
                  const status = orderStatus(o.status);
                  return (
                    <TableRow key={o.order_id}>
                      <TableCell>
                        <div className="font-mono text-sm">{o.sku}</div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {o.order_id.slice(0, 18)}
                        </div>
                      </TableCell>
                      <TableCell className="text-sm">{o.vendor_id}</TableCell>
                      <TableCell className="text-right tabular-nums">{o.qty}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatSGD(o.total_sgd)}
                      </TableCell>
                      <TableCell className="text-sm">
                        {o.expected_at ? new Date(o.expected_at).toLocaleDateString() : "—"}
                        {late && (
                          <div className="mt-1">
                            <Badge variant="default">overdue</Badge>
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant(status.kind)}>{status.label}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {o.status === "PLACED" && (
                          <Button size="sm" onClick={() => setReceiving(o)}>
                            Mark arrived
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmAll}
        onOpenChange={setConfirmAll}
        title={`Mark all ${open.length} open orders as arrived?`}
        description="This books every open order into stock at its full ordered quantity."
        confirmLabel={`Receive all ${open.length}`}
        busy={busy}
        onConfirm={() => void receiveAll()}
      />

      {receiving && (
        <ReceiveDialog
          order={receiving}
          onClose={() => setReceiving(null)}
          onDone={() => {
            setReceiving(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function ReceiveDialog({
  order,
  onClose,
  onDone,
}: {
  order: Order;
  onClose: () => void;
  onDone: () => void;
}) {
  const [qty, setQty] = useState(String(order.qty));
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const { data, error } = await inventoryClient.POST("/orders/{order_id}/receive", {
      params: { path: { order_id: order.order_id } },
      body: { qty: Number(qty), ...(expiry ? { expiry_date: expiry } : {}) },
    });
    setBusy(false);

    if (error) {
      toast.error(errorMessage(error, "Could not book the order in."));
      return;
    }
    const r = data as { qty_received?: number; sku?: string; lot_id?: string; on_hand?: number };
    toast.success(
      `Received ${r.qty_received} × ${r.sku} into lot ${r.lot_id}. On hand: ${r.on_hand}.`,
    );
    onDone();
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Receive {order.sku}</DialogTitle>
            <DialogDescription>
              {order.qty} ordered from {order.vendor_id} — {formatSGD(order.total_sgd)}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="qty">Quantity actually delivered</Label>
              <Input
                id="qty"
                type="number"
                min="1"
                max={order.qty}
                required
                autoFocus
                value={qty}
                onChange={(e) => setQty(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Short deliveries happen. Enter what physically arrived, not what was ordered.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="expiry">
                Expiry date <span className="text-muted-foreground">optional</span>
              </Label>
              <Input
                id="expiry"
                type="date"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Received stock becomes a lot with its own expiry, which is what drives FEFO
                issuing and the expiring-soon alerts. Blank defaults to 180 days.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Booking in…" : "Confirm arrival"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
