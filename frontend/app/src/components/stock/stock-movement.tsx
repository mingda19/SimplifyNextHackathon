import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage, inventoryClient } from "@/lib/api";
import type { StockItem } from "@/lib/domain";

type Lot = {
  lot_id: string;
  qty: number;
  expiry_date: string;
  source: "PURCHASED" | "DONATED";
};

type Direction = "out" | "in";

export function StockMovement({
  item,
  onClose,
  onSaved,
}: {
  item: StockItem;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [lots, setLots] = useState<Lot[]>([]);
  const [dir, setDir] = useState<Direction>("out");
  const [qty, setQty] = useState("");
  const [lotId, setLotId] = useState("");
  const [expiry, setExpiry] = useState("");
  const [source, setSource] = useState<"DONATED" | "PURCHASED">("DONATED");
  const [busy, setBusy] = useState(false);

  /**
   * Idempotency key, held across retries of the *same* submission.
   *
   * Stock movements are not safely repeatable: a retried allocate would issue
   * the goods twice. Keying on a fingerprint of the form means pressing submit
   * again after a network blip reuses the key (the service dedupes it), while
   * changing any field mints a new one so a genuinely different movement is
   * never swallowed as a duplicate.
   */
  const operation = useRef<{ fingerprint: string; key: string } | null>(null);

  useEffect(() => {
    let alive = true;
    inventoryClient
      .GET("/inventory/{sku}", { params: { path: { sku: item.sku } } })
      .then(({ data, error }) => {
        if (!alive) return;
        if (error || !data) {
          toast.error(errorMessage(error, "Could not load lots for this item."));
          return;
        }
        const list = ((data as { lots?: Lot[] }).lots ?? []) as Lot[];
        setLots(list);
        const live = list.filter((l) => l.qty > 0);
        if (live.length) setLotId(live[0].lot_id);
      });
    return () => {
      alive = false;
    };
  }, [item.sku]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = Number(qty);
    setBusy(true);

    const fingerprint = JSON.stringify([dir, n, lotId, expiry, source]);
    if (operation.current?.fingerprint !== fingerprint) {
      operation.current = { fingerprint, key: crypto.randomUUID() };
    }
    const headers = { "Idempotency-Key": operation.current.key };

    if (dir === "out") {
      const { error } = await inventoryClient.POST("/inventory/{sku}/allocate", {
        params: { path: { sku: item.sku } },
        body: { lot_id: lotId, qty: n },
        headers,
      });
      if (error) {
        setBusy(false);
        toast.error(errorMessage(error, "Could not issue that stock."));
        return;
      }
      onSaved(`Issued ${n} ${item.unit} of ${item.sku}.`);
    } else {
      const { error } = await inventoryClient.POST("/inventory/{sku}/receive", {
        params: { path: { sku: item.sku } },
        body: { qty: n, expiry_date: expiry, source },
        headers,
      });
      if (error) {
        setBusy(false);
        toast.error(errorMessage(error, "Could not receive that stock."));
        return;
      }
      onSaved(`Received ${n} ${item.unit} into ${item.sku}.`);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Stock movement — {item.sku}</DialogTitle>
          <DialogDescription>
            {item.name} — {item.on_hand} {item.unit} on hand
          </DialogDescription>
        </DialogHeader>

        <Tabs value={dir} onValueChange={(v) => setDir(v as Direction)}>
          <TabsList className="w-full">
            <TabsTrigger value="out" className="flex-1">
              Outgoing
            </TabsTrigger>
            <TabsTrigger value="in" className="flex-1">
              Incoming
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {dir === "in" && (
          <p className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-xs">
            For stock arriving against a purchase order, use <strong>Incoming orders</strong>{" "}
            instead. Receiving there books a lot with its own expiry and closes the order;
            this form only adjusts the running total.
          </p>
        )}

        <form onSubmit={submit} className="space-y-4">
          {dir === "in" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="expiry">Expiry date</Label>
                <Input
                  id="expiry"
                  type="date"
                  required
                  value={expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source">Source</Label>
                <Select
                  value={source}
                  onValueChange={(v) => setSource(v as "DONATED" | "PURCHASED")}
                >
                  <SelectTrigger id="source">
                    <SelectValue>
                      {(v: string) => (v === "PURCHASED" ? "Purchased" : "Donated")}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="DONATED">Donated</SelectItem>
                    <SelectItem value="PURCHASED">Purchased</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}

          {dir === "out" && (
            <div className="space-y-2">
              <Label htmlFor="lot">Draw from lot</Label>
              {lots.length === 0 ? (
                <p className="text-sm text-muted-foreground">No lots recorded.</p>
              ) : (
                <Select value={lotId} onValueChange={(v) => setLotId(v ?? "")}>
                  <SelectTrigger id="lot">
                    <SelectValue placeholder="Select a lot">
                      {(v: string) => {
                        const l = lots.find((x) => x.lot_id === v);
                        return l ? `${l.lot_id} — ${l.qty} left, expires ${l.expiry_date}` : v;
                      }}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {lots.map((l) => (
                      <SelectItem key={l.lot_id} value={l.lot_id}>
                        {l.lot_id} — {l.qty} left, expires {l.expiry_date} ({l.source})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="qty">
              {dir === "out" ? "Quantity to issue" : "Quantity received"}
            </Label>
            <Input
              id="qty"
              type="number"
              min="1"
              step="1"
              required
              autoFocus
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || (dir === "out" && !lotId)}>
              {busy ? "Recording…" : dir === "out" ? "Issue stock" : "Receive stock"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
