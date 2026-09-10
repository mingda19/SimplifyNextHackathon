// src/lib/api.ts
import createClient from "openapi-fetch";
import type { Middleware } from "openapi-fetch";
import type { paths as AuthPaths } from "./schema";
import type { paths as FeedbackPaths } from "./feedback-schema";
import type { paths as InventoryPaths } from "./inventory-schema";
import type { paths as OrchestratorPaths } from "./orchestrator-schema";
import type { paths as PricingPaths } from "./pricing-schema";

// No dev proxy -- each client calls its backend's own port directly (see
// each service's own `uvicorn --port` in the Makefile/README), so this is a
// cross-origin request in the browser's eyes. Every service already has
// permissive dev CORS *except* price_forecaster, which needed it added.
//
// Base URLs are bare origins, not "/api/<service>" -- unlike the old
// proxy setup, each service's own routes already start with its own prefix
// (auth's are "/auth/...", inventory's "/inventory"/"/orders"/"/vendor",
// etc.), so adding another path segment here would double it up and 404.
export const client = createClient<AuthPaths>({ baseUrl: "http://localhost:8001" });
export const feedbackClient = createClient<FeedbackPaths>({ baseUrl: "http://localhost:8002" });
export const inventoryClient = createClient<InventoryPaths>({ baseUrl: "http://localhost:8000" });
export const orchestratorClient = createClient<OrchestratorPaths>({ baseUrl: "http://localhost:8003" });
export const pricingClient = createClient<PricingPaths>({ baseUrl: "http://localhost:8004" });

/* ---------------------------------- token --------------------------------- */

const TOKEN_KEY = "pantry_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

/* ------------------------------ 401 handling ------------------------------ */

// The auth provider registers a handler here so an expired session can clear
// state and route to /login without api.ts needing to know about the router.
let unauthorizedHandler: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  unauthorizedHandler = fn;
};

// A 401 from these means "wrong credentials", not "session expired" — the page
// shows an inline error instead of us nuking the session.
const CREDENTIAL_PATHS = ["/auth/login", "/auth/signup", "/auth/change-password"];
const isCredentialAttempt = (url: string) => CREDENTIAL_PATHS.some((p) => url.includes(p));

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !isCredentialAttempt(request.url)) {
      setToken(null);
      unauthorizedHandler?.();
    }
    return response;
  },
};

client.use(authMiddleware);
feedbackClient.use(authMiddleware);
inventoryClient.use(authMiddleware);
orchestratorClient.use(authMiddleware);
pricingClient.use(authMiddleware);

/* --------------------------------- errors --------------------------------- */

/**
 * The service is down or unreachable, as opposed to it rejecting the request.
 *
 * A dev-proxy 502 or a gateway error page has a non-JSON body, so openapi-fetch
 * hands back neither `data` nor `error` and callers would otherwise report
 * something misleading about the response shape. legacy-app drew the same
 * distinction with its `offline` flag so it could name the service that was
 * down (legacy-app/src/api.js:20-23).
 */
export class ServiceUnreachable extends Error {
  constructor(service: string) {
    super(`The ${service} service is not responding.`);
    this.name = "ServiceUnreachable";
  }
}

/**
 * Throw when a request neither succeeded nor produced a parseable error body.
 * Pass the result of an openapi-fetch call plus a human name for the service.
 */
export function assertReachable(
  { error, response }: { error?: unknown; response: Response },
  service: string,
): void {
  if (!response.ok && !error) throw new ServiceUnreachable(service);
}

/**
 * Turn an openapi-fetch error into a display string.
 *
 * FastAPI returns `{detail: "..."}` for most errors and
 * `{detail: [{msg, loc, ...}]}` for request-validation failures; legacy-app
 * unwrapped both (legacy-app/src/api.js:26-37) and pages depended on it.
 */
export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof ServiceUnreachable) return error.message;

  const detail = (error as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((e) => (typeof e === "string" ? e : (e as { msg?: string })?.msg))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
