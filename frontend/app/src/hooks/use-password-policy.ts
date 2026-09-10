import { useEffect, useState } from "react";

import { client } from "@/lib/api";

/**
 * The rule list comes from the auth service rather than being hardcoded, so
 * what the user is told can never drift from what the server enforces.
 */
export function usePasswordPolicy() {
  const [rules, setRules] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    client
      .GET("/auth/password-policy")
      .then(({ data }) => {
        const r = (data as { rules?: unknown } | undefined)?.rules;
        if (alive && Array.isArray(r)) setRules(r as string[]);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return rules;
}
