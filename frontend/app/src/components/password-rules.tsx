import { useEffect, useState } from "react";
import { Check, Circle, HelpCircle } from "lucide-react";

import { client } from "@/lib/api";
import { evaluateRules } from "@/lib/password";

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

export function PasswordRules({ rules, password }: { rules: string[]; password: string }) {
  if (!rules.length) return null;

  return (
    <ul className="space-y-1">
      {evaluateRules(rules, password).map(({ rule, met, known }) => (
        <li
          key={rule}
          className={`flex items-center gap-2 text-xs ${
            met ? "text-primary" : "text-muted-foreground"
          }`}
        >
          {!known ? (
            <HelpCircle className="size-3.5 shrink-0" aria-hidden />
          ) : met ? (
            <Check className="size-3.5 shrink-0" aria-hidden />
          ) : (
            <Circle className="size-3.5 shrink-0" aria-hidden />
          )}
          <span>{rule}</span>
          {/* A rule we have no client-side predicate for: the server still enforces it. */}
          {!known && <span className="text-muted-foreground/70">(checked on submit)</span>}
        </li>
      ))}
    </ul>
  );
}
