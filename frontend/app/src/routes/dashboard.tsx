// src/routes/dashboard.tsx
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "@/lib/use-auth";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/dashboard")({
  component: DashboardPage,
});

function DashboardPage() {
  const { user, isPending, logout } = useAuth();
  const navigate = useNavigate();

  // Protect the route: If they aren't logged in, send them to /login
  useEffect(() => {
    if (!isPending && !user) {
      navigate({ to: "/login" });
    }
  }, [user, isPending, navigate]);

  if (isPending || !user) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">
            Welcome back, {user.name}. You are logged in as a {user.role}.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            logout();
            navigate({ to: "/login" });
          }}
        >
          Sign Out
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* We will build out the API fetching for these later! */}
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm">
          <h3 className="font-semibold leading-none tracking-tight mb-2">
            Public Links
          </h3>
          <p className="text-sm text-muted-foreground mb-4">
            Create access links for recipients.
          </p>
          <Button size="sm">Manage Links</Button>
        </div>
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm">
          <h3 className="font-semibold leading-none tracking-tight mb-2">
            Recipients
          </h3>
          <p className="text-sm text-muted-foreground mb-4">
            View your registered beneficiaries.
          </p>
          <Button size="sm" variant="secondary">
            View Recipients
          </Button>
        </div>
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-semibold leading-none tracking-tight mb-2">
              Public Links
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              Create password-less access links for beneficiaries.
            </p>
          </div>
          <Link to="/links">
            <Button size="sm" className="w-full">
              Manage Links
            </Button>
          </Link>
        </div>
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-semibold leading-none tracking-tight mb-2">
              Beneficiary Insights
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              Review AI-extracted unmet needs and feedback.
            </p>
          </div>
          <Link to="/feedback">
            <Button size="sm" variant="secondary" className="w-full">
              View Insights
            </Button>
          </Link>
        </div>
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-semibold leading-none tracking-tight mb-2">
              Inventory
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              Manage warehouse stock and vendor orders.
            </p>
          </div>
          <Link to="/inventory">
            <Button size="sm" variant="outline" className="w-full">
              Open Inventory
            </Button>
          </Link>
        </div>
        <div className="p-6 border rounded-xl bg-card text-card-foreground shadow-sm flex flex-col justify-between">
          <div>
            <h3 className="font-semibold leading-none tracking-tight mb-2 flex items-center gap-2">
              AI Approvals
              <span className="flex h-2 w-2 rounded-full bg-amber-500 animate-pulse"></span>
            </h3>
            <p className="text-sm text-muted-foreground mb-6">
              Review and authorize LangGraph logistical plans.
            </p>
          </div>
          <Link to="/approvals">
            <Button
              size="sm"
              variant="default"
              className="w-full bg-indigo-600 hover:bg-indigo-700"
            >
              Open Inbox
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
