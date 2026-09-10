import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage, inventoryClient } from "@/lib/api";
import type { StockItem } from "@/lib/domain";

/** Fields the agent page can pre-fill when proposing a SKU that doesn't exist yet. */
export type ItemPrefill = Partial<
  Pick<StockItem, "sku" | "name" | "category" | "unit" | "preferred_vendor_id">
>;

const BLANK = {
  sku: "",
  name: "",
  category: "",
  unit: "unit",
  reorder_point: "0",
  avg_daily_draw: "1",
  unit_cost_sgd: "0",
  preferred_vendor_id: "",
  dspi_series: "",
};

type FormState = typeof BLANK;

const toForm = (item: StockItem): FormState => ({
  sku: item.sku,
  name: item.name,
  category: item.category ?? "",
  unit: item.unit,
  reorder_point: String(item.reorder_point ?? 0),
  avg_daily_draw: String(item.avg_daily_draw ?? 0),
  unit_cost_sgd: String(item.unit_cost_sgd ?? 0),
  preferred_vendor_id: item.preferred_vendor_id ?? "",
  dspi_series: item.dspi_series ?? "",
});

/** Empty string means "not set" for a nullable column; everything else is numeric. */
const num = (v: string) => (v === "" ? null : Number(v));

/**
 * Create/edit/delete one stock item.
 *
 * Exported because the agent page reuses it to add a SKU the agent proposed but
 * the charity doesn't stock yet (legacy-app did the same via a named export
 * from Stock.jsx).
 */
export function ItemEditor({
  item,
  prefill,
  onClose,
  onSaved,
}: {
  /** null when adding a new item. */
  item: StockItem | null;
  prefill?: ItemPrefill | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const isNew = !item;
  const [form, setForm] = useState<FormState>(
    item ? toForm(item) : { ...BLANK, ...(prefill ?? {}) } as FormState,
  );
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const set = (k: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);

    const body = {
      name: form.name,
      // SKUs and categories are uppercased on save so grouping and lookups stay stable.
      category: (form.category || "").toUpperCase(),
      unit: form.unit,
      reorder_point: num(form.reorder_point),
      avg_daily_draw: num(form.avg_daily_draw),
      unit_cost_sgd: num(form.unit_cost_sgd),
      preferred_vendor_id: form.preferred_vendor_id || null,
      dspi_series: form.dspi_series || null,
    };

    if (isNew) {
      const sku = form.sku.trim().toUpperCase();
      const { error } = await inventoryClient.POST("/inventory", {
        // Opening stock is recorded as a lot via Move → Incoming, not here, so
        // that it gets an expiry date and shows up in FEFO and expiry alerts.
        body: { ...body, sku, on_hand: 0 } as never,
      });
      if (error) {
        setBusy(false);
        toast.error(errorMessage(error, `Could not add ${sku}.`));
        return;
      }
      onSaved(`Added ${sku}.`);
    } else {
      const { error } = await inventoryClient.PATCH("/inventory/{sku}", {
        params: { path: { sku: item.sku } },
        body: body as never,
      });
      if (error) {
        setBusy(false);
        toast.error(errorMessage(error, `Could not update ${item.sku}.`));
        return;
      }
      onSaved(`Updated ${item.sku}.`);
    }
  };

  const remove = async () => {
    if (!item) return;
    setBusy(true);
    const { error } = await inventoryClient.DELETE("/inventory/{sku}", {
      params: { path: { sku: item.sku } },
    });
    if (error) {
      setBusy(false);
      setConfirmDelete(false);
      toast.error(errorMessage(error, `Could not delete ${item.sku}.`));
      return;
    }
    onSaved(`Deleted ${item.sku}.`);
  };

  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={save}>
            <DialogHeader>
              <DialogTitle>{isNew ? "Add stock item" : `Edit ${item.sku}`}</DialogTitle>
            </DialogHeader>

            <div className="space-y-4 py-4">
              {isNew && (
                <div className="space-y-2">
                  <Label htmlFor="sku">SKU code</Label>
                  <Input
                    id="sku"
                    required
                    autoFocus
                    className="uppercase"
                    placeholder="SOFT-FOOD-PACK"
                    value={form.sku}
                    onChange={set("sku")}
                  />
                </div>
              )}

              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" required value={form.name} onChange={set("name")} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Input
                    id="category"
                    required
                    className="uppercase"
                    placeholder="STAPLES"
                    value={form.category}
                    onChange={set("category")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="unit">Unit</Label>
                  <Input
                    id="unit"
                    required
                    placeholder="bag"
                    value={form.unit}
                    onChange={set("unit")}
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="reorder">Reorder point</Label>
                  <Input
                    id="reorder"
                    type="number"
                    min="0"
                    required
                    value={form.reorder_point}
                    onChange={set("reorder_point")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="draw">Avg daily draw</Label>
                  <Input
                    id="draw"
                    type="number"
                    min="0"
                    required
                    value={form.avg_daily_draw}
                    onChange={set("avg_daily_draw")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cost">Unit cost (S$)</Label>
                  <Input
                    id="cost"
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={form.unit_cost_sgd}
                    onChange={set("unit_cost_sgd")}
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="vendor">
                    Preferred vendor <span className="text-muted-foreground">optional</span>
                  </Label>
                  <Input
                    id="vendor"
                    placeholder="VENDOR-HARVEST"
                    value={form.preferred_vendor_id}
                    onChange={set("preferred_vendor_id")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="dspi">
                    Price series <span className="text-muted-foreground">optional</span>
                  </Label>
                  <Input
                    id="dspi"
                    placeholder="DSPI-RICE"
                    value={form.dspi_series}
                    onChange={set("dspi_series")}
                  />
                  {/* The join key to the price forecaster; legacy-app had no field for it,
                      so it could only ever be null from the UI. */}
                  <p className="text-xs text-muted-foreground">
                    Links this item to price forecasting.
                  </p>
                </div>
              </div>

              {isNew && (
                <p className="text-xs text-muted-foreground">
                  After adding the item, use Move → Incoming to record its opening lots.
                </p>
              )}
            </div>

            <DialogFooter className="sm:justify-between">
              {!isNew ? (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy}
                >
                  Delete
                </Button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
                  Cancel
                </Button>
                <Button type="submit" disabled={busy}>
                  {busy ? "Saving…" : "Save"}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete ${item?.sku}?`}
        description="This cannot be undone."
        confirmLabel="Delete"
        destructive
        busy={busy}
        onConfirm={() => void remove()}
      />
    </>
  );
}
