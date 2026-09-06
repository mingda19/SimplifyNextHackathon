// src/routes/index.tsx
import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useAuth } from "@/lib/use-auth";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const { user, isPending } = useAuth();

  if (isPending) return <div className="p-8">Checking session...</div>;

  // If logged in, go to dashboard. If not, go to login.
  return <Navigate to={user ? "/dashboard" : "/login"} />;
}
