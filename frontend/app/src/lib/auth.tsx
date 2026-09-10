// src/lib/auth.tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  assertReachable,
  client,
  errorMessage,
  getToken,
  setToken,
  setUnauthorizedHandler,
} from "./api";

export type Role = "charity" | "recipient" | string;

/**
 * One normalized user shape.
 *
 * The two sources disagree: POST /auth/login returns the DB row
 * (`id`, `display_name`, `name`), while GET /auth/me returns the decoded JWT
 * claims (`sub`, `name`, no `id`). Normalizing here means pages never have to
 * care which one populated the session.
 */
export type User = {
  id: string;
  email: string;
  role: Role;
  name: string;
  beneficiary_id: string | null;
};

function normalizeUser(raw: unknown): User | null {
  if (!raw || typeof raw !== "object") return null;
  const u = raw as Record<string, unknown>;
  const id = u.id ?? u.sub;
  if (id == null) return null;
  return {
    id: String(id),
    email: String(u.email ?? ""),
    role: String(u.role ?? ""),
    name: String(u.name ?? u.display_name ?? u.email ?? ""),
    beneficiary_id: (u.beneficiary_id as string | null) ?? null,
  };
}

/**
 * Live auth snapshot for route guards.
 *
 * Router `beforeLoad` runs outside React rendering, so a context value captured
 * at the last render is stale for the navigation that immediately follows
 * signing in — the guard would read `user: null` and bounce straight back to
 * /login. This object has a stable identity and is mutated synchronously by the
 * provider, so guards always see the current session. Components still read
 * reactive state through useAuth().
 */
export type AuthSnapshot = { user: User | null; isPending: boolean };

export const authStore: AuthSnapshot = { user: null, isPending: true };

export type AuthValue = {
  user: User | null;
  /** True until the mount-time session check settles. Guards against a login flash on refresh. */
  isPending: boolean;
  login: (email: string, password: string) => Promise<User>;
  signup: (email: string, password: string, display_name: string) => Promise<User>;
  logout: () => void;
};

const AuthCtx = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [isPendingState, setIsPendingState] = useState(true);

  // Keep the guard snapshot and React state in lockstep. Never set one alone.
  const setUser = useCallback((u: User | null) => {
    authStore.user = u;
    setUserState(u);
  }, []);
  const setIsPending = useCallback((p: boolean) => {
    authStore.isPending = p;
    setIsPendingState(p);
  }, []);
  const isPending = isPendingState;

  // Rehydrate from the server rather than trusting decoded claims: /auth/me is
  // the only thing that proves the token is still valid and the account is
  // still active.
  useEffect(() => {
    let alive = true;
    if (!getToken()) {
      setIsPending(false);
      return;
    }
    client
      .GET("/auth/me")
      .then(({ data, error }) => {
        if (!alive) return;
        if (error || !data) {
          setToken(null);
          return;
        }
        setUser(normalizeUser((data as { user?: unknown }).user));
      })
      .catch(() => alive && setToken(null)) // expired or invalid — start clean
      .finally(() => alive && setIsPending(false));
    return () => {
      alive = false;
    };
    // setUser/setIsPending are stable useCallbacks; this runs once on mount.
  }, [setUser, setIsPending]);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, [setUser]);

  // A 401 on any request means the session died mid-use. Clear it here so the
  // whole app sees it; route guards then bounce to /login.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    return () => setUnauthorizedHandler(null);
  }, [setUser]);

  const login = useCallback(async (email: string, password: string) => {
    const { data, error, response } = await client.POST("/auth/login", {
      body: { email, password },
    });
    assertReachable({ error, response }, "accounts");
    if (error) throw new Error(errorMessage(error, "Could not sign in"));
    const payload = data as { token?: string; user?: unknown };
    const next = normalizeUser(payload?.user);
    if (!payload?.token || !next) throw new Error("Sign-in response was malformed");
    setToken(payload.token);
    setUser(next);
    return next;
  }, [setUser]);

  const signup = useCallback(
    async (email: string, password: string, display_name: string) => {
      const { data, error, response } = await client.POST("/auth/signup", {
        // Self-signup is charity-only; recipients are invited by a charity.
        body: { email, password, display_name, role: "charity" },
      });
      assertReachable({ error, response }, "accounts");
      if (error) throw new Error(errorMessage(error, "Could not create account"));
      const payload = data as { token?: string; user?: unknown };
      const next = normalizeUser(payload?.user);
      if (!payload?.token || !next) throw new Error("Sign-up response was malformed");
      setToken(payload.token);
      setUser(next);
      return next;
    },
    [setUser],
  );

  const value = useMemo<AuthValue>(
    () => ({ user, isPending, login, signup, logout }),
    [user, isPending, login, signup, logout],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

/** Where a user belongs after signing in. Charity staff run operations; everyone else files requests. */
export const homeRouteFor = (user: User | null) =>
  user?.role === "charity" ? "/stock" : "/request";
