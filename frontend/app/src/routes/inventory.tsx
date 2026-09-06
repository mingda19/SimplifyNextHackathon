// src/routes/inventory.tsx
import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { inventoryClient } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Package, AlertCircle, ShoppingCart } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/inventory")({
  component: InventoryPage,
});

function InventoryPage() {
  const [inventory, setInventory] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchInventory = async () => {
    setIsLoading(true);
    const [invRes, alertRes] = await Promise.all([
      inventoryClient.GET("/inventory"),
      inventoryClient.GET("/inventory/alerts"),
    ]);

    if (invRes.error) toast.error("Failed to load inventory");
    else setInventory(invRes.data || []);

    if (!alertRes.error) setAlerts(alertRes.data || []);

    setIsLoading(false);
  };

  useEffect(() => {
    fetchInventory();
  }, []);

  // Action: Request a quote from the vendor
  const handleRequestQuote = async (sku: string, vendorId: string) => {
    const { data, error } = await inventoryClient.POST("/vendor/{id}/quote", {
      params: { path: { id: vendorId } },
      body: { sku, qty: 50 }, // Hardcoding 50 for the demo
    });

    if (error) {
      toast.error("Vendor quote failed");
    } else {
      toast.success(
        `Quote received! $${data.total_price_sgd} SGD for 50 units.`,
      );
    }
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Inventory Management
          </h1>
          <p className="text-muted-foreground mt-1">
            Monitor stock levels and manage vendor orders.
          </p>
        </div>
        <Button className="gap-2">
          <Package className="h-4 w-4" /> Add Item
        </Button>
      </div>

      {/* ALERTS SECTION */}
      {alerts.length > 0 && (
        <Card className="border-destructive/50 bg-destructive/5 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-destructive text-lg">
              <AlertCircle className="h-5 w-5" />
              Action Required: Low Stock
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              {alerts.map((alert, idx) => (
                <div
                  key={idx}
                  className="flex justify-between items-center bg-white p-3 rounded-md border border-destructive/20 shadow-sm"
                >
                  <div>
                    <span className="font-semibold">
                      {alert.name || alert.sku}
                    </span>
                    <span className="text-muted-foreground text-sm ml-2">
                      Currently at {alert.on_hand} {alert.unit}s (Below reorder
                      point of {alert.reorder_point})
                    </span>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-destructive text-destructive hover:bg-destructive hover:text-white"
                    onClick={() =>
                      handleRequestQuote(
                        alert.sku,
                        alert.preferred_vendor_id || "VENDOR-1",
                      )
                    }
                  >
                    Draft Restock Order
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* MAIN INVENTORY TABLE */}
      <Card className="shadow-sm border-stone-200">
        <CardHeader>
          <CardTitle>Current Stock</CardTitle>
          <CardDescription>
            All items currently tracked in the warehouse.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SKU</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-center">On Hand</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8">
                    Loading stock...
                  </TableCell>
                </TableRow>
              ) : inventory.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center py-8 text-stone-500"
                  >
                    No inventory found.
                  </TableCell>
                </TableRow>
              ) : (
                inventory.map((item) => (
                  <TableRow key={item.sku}>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {item.sku}
                    </TableCell>
                    <TableCell className="font-medium text-stone-800">
                      {item.name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-normal">
                        {item.category}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-center">
                      <span
                        className={`font-mono font-medium ${item.on_hand <= item.reorder_point ? "text-destructive" : "text-emerald-600"}`}
                      >
                        {item.on_hand}
                      </span>
                      <span className="text-xs text-muted-foreground ml-1">
                        {item.unit}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-primary hover:text-primary hover:bg-primary/10"
                        onClick={() =>
                          handleRequestQuote(
                            item.sku,
                            item.preferred_vendor_id || "VENDOR-1",
                          )
                        }
                      >
                        <ShoppingCart className="h-4 w-4 mr-1" /> Quote
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
