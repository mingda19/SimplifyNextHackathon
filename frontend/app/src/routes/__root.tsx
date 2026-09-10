import { Toaster } from "@/components/ui/sonner";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { TanStackRouterDevtools } from "@tanstack/router-devtools";
import type { RouterContext } from "@/lib/router-context";

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <>
      <Outlet />
      <Toaster richColors position="top-center" />
      <TanStackRouterDevtools />
    </>
  ),
});
