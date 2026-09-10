// src/routes/index.tsx
import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * Landing route: send people where they actually work. Charity staff run
 * operations from /stock; everyone else files requests.
 *
 * Safe as a synchronous beforeLoad because main.tsx holds the router back until
 * the session check settles.
 */
export const Route = createFileRoute("/")({
  beforeLoad: ({ context }) => {
    const { user } = context.auth;
    if (!user) throw redirect({ to: "/login" });
    throw redirect({ to: user.role === "charity" ? "/stock" : "/request" });
  },
});
