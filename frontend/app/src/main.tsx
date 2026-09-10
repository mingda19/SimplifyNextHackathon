import { StrictMode, useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import "./index.css";

import { AuthProvider, authStore, useAuth } from "@/lib/auth";
// Import the auto-generated route tree
import { routeTree } from "./routeTree.gen";

// authStore has a stable identity and is mutated synchronously by the provider,
// so a guard running during the navigation that follows sign-in sees the new
// session rather than the last render's snapshot.
const router = createRouter({
  routeTree,
  context: { auth: authStore },
  defaultPreload: "intent",
});

// Register the router instance for type safety
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

/**
 * Hold the router back until the session check settles.
 *
 * Route guards read `context.auth.user`, so rendering them mid-check would
 * bounce a signed-in user to /login on every refresh. legacy-app solved the
 * same problem with a "Loading…" splash inside its Protected wrapper.
 */
function InnerApp() {
  const auth = useAuth();

  // Re-evaluate guards when the session *changes* — e.g. a 401 clears it
  // mid-use. Must run before any early return so hook order stays stable.
  //
  // Deliberately skipped while pending and on the first settle: invalidating
  // during the initial session check would resolve the requested route against
  // a null user and redirect to /login before RouterProvider ever mounts,
  // which loses the session on every hard refresh.
  const settled = useRef(false);
  useEffect(() => {
    if (auth.isPending) return;
    if (!settled.current) {
      settled.current = true;
      return;
    }
    void router.invalidate();
  }, [auth.user, auth.isPending]);

  if (auth.isPending) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return <RouterProvider router={router} />;
}

const rootElement = document.getElementById("root")!;
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <StrictMode>
      <AuthProvider>
        <InnerApp />
      </AuthProvider>
    </StrictMode>,
  );
}
