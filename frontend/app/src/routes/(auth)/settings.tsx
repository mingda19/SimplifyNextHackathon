import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordRules } from "@/components/password-rules";
import { usePasswordPolicy } from "@/hooks/use-password-policy";
import { client, errorMessage, inventoryClient } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { allRulesMet } from "@/lib/password";

export const Route = createFileRoute("/(auth)/settings")({
  component: SettingsPage,
});

type SettingsResponse = {
  monthly_budget_sgd: string;
  updated_at: string;
  updated_by?: string | null;
};

function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Signed in as {user?.name} ({user?.email}).
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <BudgetCard />
        <PasswordCard />
      </div>
    </div>
  );
}

function BudgetCard() {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState<SettingsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    inventoryClient
      .GET("/settings")
      .then(({ data, error }) => {
        if (!alive) return;
        if (error || !data) {
          toast.error(errorMessage(error, "Could not load the budget."));
          return;
        }
        const s = data as SettingsResponse;
        setSaved(s);
        setValue(String(s.monthly_budget_sgd));
      })
      .finally(() => alive && setIsLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) {
      toast.error("Enter a positive amount.");
      return;
    }
    setIsSaving(true);
    const { data, error } = await inventoryClient.PATCH("/settings", {
      body: { monthly_budget_sgd: n },
    });
    setIsSaving(false);

    if (error || !data) {
      toast.error(errorMessage(error, "Could not save the budget."));
      return;
    }
    const s = data as SettingsResponse;
    setSaved(s);
    setValue(String(s.monthly_budget_sgd));
    toast.success("Budget saved.");
  };

  return (
    <Card>
      <form onSubmit={submit}>
        <CardHeader>
          <CardTitle>Monthly procurement budget</CardTitle>
          <CardDescription>
            The agent cannot place an order that would push this month's total spend past
            this amount — enforced by the inventory service at commit time, not just shown
            here for reference.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="budget">S$ per month</Label>
          <Input
            id="budget"
            type="number"
            min="1"
            step="0.01"
            required
            disabled={isLoading}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </CardContent>
        <CardFooter className="flex-col items-start gap-2">
          <Button type="submit" disabled={isSaving || isLoading}>
            {isSaving ? "Saving…" : "Save budget"}
          </Button>
          {saved?.updated_at && (
            <p className="text-xs text-muted-foreground">
              Last changed {new Date(saved.updated_at).toLocaleString()}
              {saved.updated_by ? ` by ${saved.updated_by}` : ""}.
            </p>
          )}
        </CardFooter>
      </form>
    </Card>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const rules = usePasswordPolicy();

  const matches = next.length > 0 && next === confirm;
  const canSubmit = allRulesMet(rules, next) && matches;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!matches) {
      toast.error("New password and confirmation do not match.");
      return;
    }
    setIsSaving(true);
    const { error } = await client.POST("/auth/change-password", {
      body: { current_password: current, new_password: next },
    });
    setIsSaving(false);

    if (error) {
      toast.error(errorMessage(error, "Could not change the password."));
      return;
    }
    toast.success("Password changed.");
    setCurrent("");
    setNext("");
    setConfirm("");
  };

  return (
    <Card>
      <form onSubmit={submit}>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>
            You will stay signed in on this device after changing it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="cur">Current password</Label>
            <Input
              id="cur"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new">New password</Label>
            <Input
              id="new"
              type="password"
              autoComplete="new-password"
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <PasswordRules rules={rules} password={next} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">Confirm new password</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            {confirm.length > 0 && !matches && (
              <p className="text-xs text-destructive">Does not match the new password.</p>
            )}
          </div>
        </CardContent>
        <CardFooter>
          <Button type="submit" disabled={isSaving || !canSubmit}>
            {isSaving ? "Changing…" : "Change password"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
