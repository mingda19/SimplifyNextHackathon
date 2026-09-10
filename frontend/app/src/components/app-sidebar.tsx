import { useEffect, useState } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Bot,
  LayoutDashboard,
  MessageSquareHeart,
  Package,
  Settings as SettingsIcon,
  Truck,
  Users,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { inventoryClient, orchestratorClient } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const NAV = [
  { to: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { to: "/stock", label: "Stock", icon: Package },
  { to: "/orders", label: "Incoming orders", icon: Truck, badge: "orders" },
  { to: "/agent", label: "Agent actions", icon: Bot, badge: "pending" },
  { to: "/feedback", label: "Beneficiary needs", icon: MessageSquareHeart },
  { to: "/people", label: "People & links", icon: Users },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

/**
 * The pending-approval count is the one number a charity needs at a glance: it
 * is work the agent has queued and cannot do without a human. Polled here
 * rather than per-page so it stays visible wherever you are.
 */
function useOpsCounts() {
  const [counts, setCounts] = useState({ pending: 0, orders: 0 });

  useEffect(() => {
    let alive = true;
    const poll = () => {
      orchestratorClient
        .GET("/agent/runs", { params: { query: { status: "pending_approval" } } })
        .then(({ data }) => {
          if (alive && Array.isArray(data))
            setCounts((c) => ({ ...c, pending: data.length }));
        })
        .catch(() => {});
      inventoryClient
        .GET("/orders", { params: { query: { status: "PLACED" } } })
        .then(({ data }) => {
          if (alive && Array.isArray(data)) setCounts((c) => ({ ...c, orders: data.length }));
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 8000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return counts;
}

export function AppSidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const counts = useOpsCounts();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-3">
        <span className="text-lg font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
          Pantry<span className="text-primary">.</span>
        </span>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => {
                const count = "badge" in item ? counts[item.badge] : 0;
                return (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      render={<Link to={item.to} />}
                      isActive={pathname.startsWith(item.to)}
                      tooltip={item.label}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                    {count > 0 && <SidebarMenuBadge>{count}</SidebarMenuBadge>}
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-2 group-data-[collapsible=icon]:hidden">
        <div className="min-w-0 px-2">
          <p className="truncate text-sm font-medium">{user?.name}</p>
          <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => {
            logout();
            navigate({ to: "/login", replace: true });
          }}
        >
          Sign out
        </Button>
      </SidebarFooter>
    </Sidebar>
  );
}
