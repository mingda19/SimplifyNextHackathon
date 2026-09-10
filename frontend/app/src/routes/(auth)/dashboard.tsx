import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ArrowRight, Bot, Package, Truck, MessageSquareHeart } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { feedbackClient, inventoryClient, orchestratorClient } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  formatSGDWhole,
  stockValue,
  type StockAlert,
  type StockItem,
} from "@/lib/domain";

export const Route = createFileRoute("/(auth)/dashboard")({
  component: DashboardPage,
});

type Counts = {
  lowStock: number;
  expiring: number;
  value: number;
  openOrders: number;
  pendingApprovals: number;
  unmetNeeds: number;
};

function StatCard({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string;
  value: string | number;
  hint?: string;
  emphasis?: "danger" | "warn";
}) {
  const tone =
    emphasis === "danger"
      ? "text-destructive"
      : emphasis === "warn"
        ? "text-primary"
        : "text-foreground";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`text-3xl tabular-nums ${tone}`}>{value}</CardTitle>
      </CardHeader>
      {hint && (
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">{hint}</p>
        </CardContent>
      )}
    </Card>
  );
}

function ShortcutCard({
  title,
  description,
  to,
  cta,
  icon: Icon,
}: {
  title: string;
  description: string;
  to: string;
  cta: string;
  icon: typeof Package;
}) {
  return (
    <Card className="flex flex-col justify-between">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="size-4 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button render={<Link to={to} />} size="sm" variant="outline" className="w-full">
          {cta}
          <ArrowRight className="size-3.5" />
        </Button>
      </CardContent>
    </Card>
  );
}

function DashboardPage() {
  const { user } = useAuth();
  const [counts, setCounts] = useState<Counts | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([
      inventoryClient.GET("/inventory"),
      inventoryClient.GET("/inventory/alerts"),
      inventoryClient.GET("/orders", { params: { query: { status: "PLACED" } } }),
      orchestratorClient.GET("/agent/runs", {
        params: { query: { status: "pending_approval" } },
      }),
      feedbackClient.GET("/feedback/unmet-needs"),
    ])
      .then(([stock, alertRes, orders, runs, needs]) => {
        if (!alive) return;
        const items = (Array.isArray(stock.data) ? stock.data : []) as StockItem[];
        const alerts = (Array.isArray(alertRes.data) ? alertRes.data : []) as StockAlert[];
        const ranked = (needs.data as { ranked?: unknown[] } | undefined)?.ranked ?? [];
        setCounts({
          lowStock: items.filter((it) => it.on_hand < it.reorder_point).length,
          expiring: new Set(
            alerts.filter((a) => a.type === "EXPIRING_SOON").map((a) => a.sku),
          ).size,
          value: stockValue(items),
          openOrders: Array.isArray(orders.data) ? orders.data.length : 0,
          pendingApprovals: Array.isArray(runs.data) ? runs.data.length : 0,
          unmetNeeds: ranked.length,
        });
      })
      .catch(() => alive && setCounts(null));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="text-sm text-muted-foreground">
          Welcome back, {user?.name}. Here is where things stand right now.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {counts === null ? (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)
        ) : (
          <>
            <StatCard
              label="Below reorder point"
              value={counts.lowStock}
              hint="Items that need restocking"
              emphasis={counts.lowStock > 0 ? "danger" : undefined}
            />
            <StatCard
              label="Needs your approval"
              value={counts.pendingApprovals}
              hint="Agent runs waiting on a decision"
              emphasis={counts.pendingApprovals > 0 ? "warn" : undefined}
            />
            <StatCard
              label="Orders on the way"
              value={counts.openOrders}
              hint="Placed but not yet received"
            />
            <StatCard
              label="Stock value at cost"
              value={formatSGDWhole(counts.value)}
              hint={`${counts.expiring} SKU${counts.expiring === 1 ? "" : "s"} expiring soon`}
            />
          </>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ShortcutCard
          title="Stock"
          description="Browse stock by category and record movements in or out."
          to="/stock"
          cta="Open stock"
          icon={Package}
        />
        <ShortcutCard
          title="Agent actions"
          description="Review the plans the agent has queued and approve or decline them."
          to="/agent"
          cta="Open inbox"
          icon={Bot}
        />
        <ShortcutCard
          title="Incoming orders"
          description="Track purchase orders and mark them as arrived."
          to="/orders"
          cta="View orders"
          icon={Truck}
        />
        <ShortcutCard
          title="Beneficiary needs"
          description="Read ranked unmet needs extracted from beneficiary messages."
          to="/feedback"
          cta="View needs"
          icon={MessageSquareHeart}
        />
      </div>
    </div>
  );
}
