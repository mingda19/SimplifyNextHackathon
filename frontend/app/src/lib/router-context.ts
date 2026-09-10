import type { AuthSnapshot } from "./auth";

/**
 * Context available to every route's `beforeLoad`/`loader`.
 *
 * Kept in its own module rather than in main.tsx: the route tree imports it,
 * and main.tsx imports the route tree, so declaring it there is a cycle and
 * costs Fast Refresh on every edit.
 */
export type RouterContext = { auth: AuthSnapshot };
