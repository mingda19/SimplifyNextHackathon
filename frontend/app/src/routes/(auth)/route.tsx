import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

import { AppSidebar } from "@/components/app-sidebar";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";

/**
 * Pathless layout wrapping every staff-facing page: sidebar chrome plus the
 * signed-in guard. Auth screens and the public request form sit outside it.
 *
 * The guard is safe to run synchronously because main.tsx holds the router back
 * until the session check settles, so `context.auth.user` is never
 * "not known yet" here.
 */
export const Route = createFileRoute("/(auth)")({
  beforeLoad: ({ context }) => {
    const { user } = context.auth;
    if (!user) throw redirect({ to: "/login" });
    // Cosmetic only — services/auth's require_charity is the real boundary.
    if (user.role !== "charity") throw redirect({ to: "/request" });
  },
  component: AppLayout,
});

function AppLayout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
        </header>
        <main className="mx-auto w-full max-w-[1180px] flex-1 p-6">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
