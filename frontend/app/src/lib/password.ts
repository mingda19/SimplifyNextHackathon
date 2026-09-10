// src/lib/password.ts
//
// The rule list is fetched from GET /auth/password-policy rather than hardcoded,
// so what the user is told can never drift from what the server enforces. These
// predicates only mirror those rules for live feedback as they type.

export const PASSWORD_CHECKS: Record<string, (p: string) => boolean> = {
  "at least 10 characters": (p) => p.length >= 10,
  "an uppercase letter": (p) => /[A-Z]/.test(p),
  "a lowercase letter": (p) => /[a-z]/.test(p),
  "a number": (p) => /\d/.test(p),
};

export type RuleState = {
  rule: string;
  met: boolean;
  /** False when the server sent a rule we have no client-side predicate for. */
  known: boolean;
};

/**
 * The predicates are keyed by the server's exact rule strings, so an upstream
 * wording change silently orphans one. legacy-app treated an orphaned rule as
 * permanently unmet, which disabled the submit button forever with no
 * explanation (Signup.jsx:26). Here an unknown rule is reported as unknown and
 * left to the server to enforce, so the worst case is a clear 422 instead of a
 * dead button.
 */
export function evaluateRules(rules: string[], password: string): RuleState[] {
  return rules.map((rule) => {
    const check = PASSWORD_CHECKS[rule];
    return check
      ? { rule, met: check(password), known: true }
      : { rule, met: false, known: false };
  });
}

/** Whether every rule we can actually verify passes. Unknown rules don't block. */
export function allRulesMet(rules: string[], password: string): boolean {
  if (!password) return false;
  const states = evaluateRules(rules, password);
  if (!states.length) return false;
  return states.every((s) => !s.known || s.met);
}
