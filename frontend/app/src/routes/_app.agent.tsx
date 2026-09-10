// src/routes/approvals.tsx
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { orchestratorClient } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import {
  Bot,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  ChevronDown,
  Loader2,
  RefreshCw,
  Eye,
  EyeOff,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "cn";

export const Route = createFileRoute("/_app/agent")({
  component: ApprovalsPage,
});

// Real backend status values (see services/orchestrator/api.py) -- the
// previous version of this page checked for "paused", which the API never
// actually returns, so nothing here ever rendered as awaiting approval.
const STATUS: Record<string, { label: string; className: string }> = {
  running: { label: "running", className: "bg-stone-100 text-stone-600 border-stone-200" },
  pending_approval: { label: "needs your approval", className: "bg-amber-100 text-amber-800 border-amber-200" },
  committing: { label: "decision in progress", className: "bg-amber-100 text-amber-800 border-amber-200" },
  approved: { label: "approved", className: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  rejected: { label: "rejected", className: "bg-stone-100 text-stone-500 border-stone-200" },
  failed: { label: "failed", className: "bg-red-100 text-red-700 border-red-200" },
  completed: { label: "no action needed", className: "bg-emerald-100 text-emerald-800 border-emerald-200" },
};

function ApprovalsPage() {
  const { user } = useAuth();
  const [runs, setRuns] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [openThread, setOpenThread] = useState<string | null>(null);
  const [charityType, setCharityType] = useState<"A" | "B">("B");
  const [busy, setBusy] = useState(false);
  const [watchState, setWatchState] = useState<any | null>(null);
  const [watchBusy, setWatchBusy] = useState(false);

  const fetchRuns = async () => {
    const { data, error } = await orchestratorClient.GET("/agent/runs");
    if (error) {
      toast.error("Failed to load agent runs");
    } else {
      setRuns(Array.isArray(data) ? data : []);
    }
    setIsLoading(false);
  };

  const fetchWatch = async () => {
    const { data } = await orchestratorClient.GET("/agent/watch");
    if (data) setWatchState(data);
  };

  useEffect(() => {
    fetchRuns();
    fetchWatch();
    // A run takes tens of seconds against live Bedrock; poll so the queue
    // (and watch-mode status) updates without a manual refresh. Watch mode
    // itself polls server-side every WATCH_POLL_SECONDS (60s) -- this 5s
    // interval is just the UI catching up on what it already decided.
    const id = setInterval(() => {
      fetchRuns();
      fetchWatch();
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const startRun = async () => {
    setBusy(true);
    const { error } = await orchestratorClient.POST("/agent/runs", {
      body: { charity_type: charityType },
    });
    if (error) {
      toast.error("Failed to start AI run");
    } else {
      toast.success("Agent run started — it will appear below when it needs you.");
      fetchRuns();
    }
    setBusy(false);
  };

  const toggleWatch = async () => {
    setWatchBusy(true);
    const active = !watchState?.active;
    const { data, error } = await orchestratorClient.POST("/agent/watch", {
      body: { active, charity_type: charityType },
    });
    if (error) {
      toast.error(active ? "Failed to activate the agent" : "Failed to deactivate the agent");
    } else {
      setWatchState(data);
      toast.success(
        active
          ? "Agent activated — it will act on its own when 10+ feedback messages arrive or inventory shifts a lot."
          : "Agent deactivated.",
      );
    }
    setWatchBusy(false);
  };

  const decide = async (
    threadId: string,
    decision: "approved" | "rejected",
    approvedSteps?: number[],
  ) => {
    setBusy(true);
    const { data, error } = await orchestratorClient.POST(
      "/agent/runs/{thread_id}/decision",
      {
        params: { path: { thread_id: threadId } },
        body: {
          decision,
          decided_by: user?.email || "unknown",
          ...(approvedSteps !== undefined ? { approved_steps: approvedSteps } : {}),
        },
      },
    );
    if (error) {
      toast.error(`Failed to submit decision for ${threadId}`);
    } else {
      const outcome = (data as any)?.outcome;
      const declined = outcome?.declined_steps?.length || 0;
      const resolved = outcome?.feedback_resolved || 0;
      toast.success(
        decision === "approved"
          ? `Approved${declined ? ` (${declined} line${declined > 1 ? "s" : ""} declined)` : ""}. ` +
            (outcome?.kind === "purchase_order"
              ? `Committed S$${(outcome.total_sgd ?? 0).toFixed(2)}.`
              : outcome?.kind === "acquisition_checklist"
                ? "Checklist issued."
                : "No orders were committed — check the failure details.") +
            (resolved ? ` ${resolved} beneficiary message${resolved > 1 ? "s" : ""} marked resolved.` : "")
          : "Rejected — nothing was committed.",
      );
      setOpenThread(null);
      fetchRuns();
    }
    setBusy(false);
  };

  const openRun = runs.find((r) => r.thread_id === openThread) || null;
  const pending = runs.filter((r) => r.status === "pending_approval");

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">AI Agent Approvals</h1>
          <p className="text-muted-foreground mt-1">
            The agent senses stock, beneficiary needs and prices, then queues a
            plan. Nothing is committed until you approve it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Funding type"
            value={charityType}
            onChange={(e) => setCharityType(e.target.value as "A" | "B")}
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="B">Budget funded — purchase orders</option>
            <option value="A">Donation fed — checklist</option>
          </select>
          <Button onClick={startRun} disabled={busy} className="gap-2 bg-indigo-600 hover:bg-indigo-700">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
            Run agent now
          </Button>
          <Button
            onClick={toggleWatch}
            disabled={watchBusy}
            variant={watchState?.active ? "default" : "outline"}
            className={cn("gap-2", watchState?.active && "bg-emerald-600 hover:bg-emerald-700")}
          >
            {watchBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : watchState?.active ? (
              <Eye className="h-4 w-4" />
            ) : (
              <EyeOff className="h-4 w-4" />
            )}
            {watchState?.active ? "Agent active" : "Activate agent"}
          </Button>
        </div>
      </div>

      {watchState?.active && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 flex items-center gap-2">
          <Eye className="h-4 w-4 shrink-0" />
          <span>
            Watching for 10+ new feedback messages or a big inventory shift — checking every minute.
            {watchState.last_poll_at && (
              <span className="text-emerald-600">
                {" "}
                Last checked {new Date(watchState.last_poll_at).toLocaleTimeString()}.
              </span>
            )}
            {watchState.last_trigger_at && (
              <span className="text-emerald-600"> Last acted {new Date(watchState.last_trigger_at).toLocaleTimeString()}.</span>
            )}
            {" "}Deactivates on its own after {watchState.quiet_cycles ?? 0}/2 quiet cycles with nothing to act on.
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard n={pending.length} label="awaiting approval" warn={pending.length > 0} />
        <StatCard n={runs.filter((r) => r.status === "approved").length} label="approved" />
        <StatCard n={runs.filter((r) => r.status === "rejected").length} label="rejected" />
        <StatCard
          n={runs.filter((r) => r.status === "failed").length}
          label="failed"
          warn={runs.some((r) => r.status === "failed")}
        />
      </div>

      <div className="grid gap-4">
        {isLoading ? (
          <p className="text-stone-500 py-8 text-center animate-pulse">Loading AI workflows...</p>
        ) : runs.length === 0 ? (
          <Card className="border-stone-200 border-dashed shadow-none">
            <CardContent className="flex flex-col items-center justify-center h-48 text-stone-500">
              <Bot className="h-12 w-12 text-stone-300 mb-4" />
              <p>No agent runs yet. Use <strong>Run agent now</strong> to start one.</p>
            </CardContent>
          </Card>
        ) : (
          runs.map((run) => {
            const s = STATUS[run.status] || STATUS.running;
            const predicted = run.summary?.predicted;
            const total = run.summary?.queued?.total_sgd;
            return (
              <Card
                key={run.thread_id}
                className={cn(
                  "shadow-sm border-stone-200",
                  run.status === "pending_approval" && "border-amber-300 ring-1 ring-amber-100",
                )}
              >
                <CardHeader className="pb-3 flex flex-row justify-between items-start">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <CardTitle className="text-lg">Workflow Run</CardTitle>
                      <Badge variant="outline" className="font-mono text-xs bg-stone-50">
                        {run.thread_id}
                      </Badge>
                    </div>
                    <CardDescription>
                      {run.error
                        ? run.error.slice(0, 100)
                        : predicted?.stockout_sku
                          ? <>Restock <strong>{predicted.stockout_sku}</strong> — fails in {predicted.days_until_failure}d</>
                          : "Review the agent's proposed plan."}
                    </CardDescription>
                  </div>
                  <Badge className={cn("gap-1.5 px-3 py-1 text-sm font-medium border", s.className)}>
                    {run.status === "pending_approval" || run.status === "committing" ? (
                      <Clock className="h-3.5 w-3.5" />
                    ) : run.status === "approved" || run.status === "completed" ? (
                      <CheckCircle className="h-3.5 w-3.5" />
                    ) : run.status === "failed" ? (
                      <AlertTriangle className="h-3.5 w-3.5" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5" />
                    )}
                    {s.label}
                  </Badge>
                </CardHeader>
                <CardContent>
                  <div className="bg-stone-50 border border-stone-100 rounded-lg p-4 text-sm text-stone-700 flex items-center justify-between">
                    <span>
                      {(run.summary?.queued?.steps || []).length} step(s) queued
                      {total ? ` · S$${Number(total).toFixed(2)}` : ""}
                    </span>
                  </div>
                </CardContent>
                <CardFooter className="justify-end gap-3 pt-0">
                  {run.status === "pending_approval" ? (
                    <Button onClick={() => setOpenThread(run.thread_id)} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                      Review plan
                    </Button>
                  ) : (
                    <Button variant="outline" onClick={() => setOpenThread(run.thread_id)}>
                      View details
                    </Button>
                  )}
                </CardFooter>
              </Card>
            );
          })
        )}
      </div>

      <RunDetailDialog
        run={openRun}
        open={openThread !== null}
        busy={busy}
        onClose={() => setOpenThread(null)}
        onDecide={decide}
      />
    </div>
  );
}

function StatCard({ n, label, warn }: { n: number; label: string; warn?: boolean }) {
  return (
    <Card className={cn("shadow-none", warn && n > 0 && "border-amber-300")}>
      <CardContent className="p-4">
        <div className={cn("text-2xl font-bold", warn && n > 0 && "text-amber-700")}>{n}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  );
}

function RunDetailDialog({
  run,
  open,
  busy,
  onClose,
  onDecide,
}: {
  run: any | null;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onDecide: (threadId: string, decision: "approved" | "rejected", approvedSteps?: number[]) => void;
}) {
  const s = run?.summary || {};
  const sensed = s.sensed || {};
  const predicted = s.predicted || {};
  const queued = s.queued || {};
  const adaptations: any[] = s.adaptations || [];
  const guardrails = s.guardrails || {};
  const steps: any[] = queued.steps || [];
  const pending = run?.status === "pending_approval";

  const actionableSteps = steps.filter((st) => st.action !== "flag_for_human");
  const flagSteps = steps.filter((st) => st.action === "flag_for_human");

  const [picked, setPicked] = useState<number[]>([]);
  const [reviewedFlags, setReviewedFlags] = useState<Set<number>>(new Set());

  // Reset selection whenever a different run is opened.
  useEffect(() => {
    if (!run) return;
    setPicked(actionableSteps.map((st, i) => st.index ?? i));
    setReviewedFlags(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.thread_id]);

  if (!run) return null;

  const selectedTotal = actionableSteps
    .filter((st, i) => picked.includes(st.index ?? i))
    .reduce((t, st) => t + (st.value_sgd || 0), 0);

  const allFlagsReviewed = flagSteps.every((st, i) => reviewedFlags.has(st.index ?? i));
  // Flagged items require an explicit review before approval is even
  // possible -- previously you could tick "Approve" without touching them at
  // all, since they were just another pre-checked row in the same list.
  const canApprove = pending && picked.length + flagSteps.length > 0 && allFlagsReviewed;

  const approve = () => {
    const flagIdx = flagSteps.map((st, i) => st.index ?? i);
    onDecide(run.thread_id, "approved", [...picked, ...flagIdx].sort((a, b) => a - b));
  };

  const moqAdaptations = adaptations.filter((a) => a.error_code === "MOQ_NOT_MET");
  const otherAdaptations = adaptations.filter((a) => a.error_code !== "MOQ_NOT_MET");

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Agent plan</DialogTitle>
          <DialogDescription className="font-mono text-xs">{run.thread_id}</DialogDescription>
        </DialogHeader>

        {guardrails.halt_reason && <Banner tone="err">{guardrails.halt_reason}</Banner>}
        {run.error && <Banner tone="err">{run.error}</Banner>}
        {guardrails.exceeds_single_order_cap && (
          <Banner tone="warn">
            One order line exceeds the single-order cap of S${guardrails.baselines?.max_single_order_sgd}.
          </Banner>
        )}

        <Section title="What it sensed">
          <ul className="text-sm space-y-1 text-stone-700">
            <li>{(sensed.below_reorder || []).length} item(s) below reorder point</li>
            <li>{(sensed.expiring_soon || []).length} lot(s) expiring soon</li>
            {(sensed.top_unmet_needs || []).map((n: any, i: number) => (
              <li key={i}>
                "{n.need}" — {n.frequency} beneficiary/ies, urgency {n.urgency}
                {n.gap && <Badge variant="outline" className="ml-2 text-red-700 border-red-200">no stocked SKU</Badge>}
              </li>
            ))}
            {(sensed.price_signals || []).map((p: any, i: number) => (
              <li key={`p${i}`}>
                {p.series} prices {p.direction} ({p.pct_change_3m}% / 3mo) → <strong>{p.recommendation}</strong>
                <span className="text-muted-foreground"> · {Math.round((p.confidence || 0) * 100)}% confidence</span>
              </li>
            ))}
            {(sensed.unavailable_services || []).length > 0 && (
              <li className="text-muted-foreground">Reasoned without: {sensed.unavailable_services.join(", ")}</li>
            )}
          </ul>
        </Section>

        <Section title="What it predicts">
          <p className="text-sm text-stone-700">{predicted.reasoning || "—"}</p>
        </Section>

        <Section title="What it has queued">
          <p className="text-xs text-muted-foreground mb-2">
            {pending
              ? "Tick the lines you want committed. Unticked lines are not ordered."
              : "Unticked lines were declined and not ordered."}
          </p>
          {actionableSteps.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing queued for purchase.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8"></TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead>Vendor</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {actionableSteps.map((st, i) => {
                  const idx = st.index ?? i;
                  const on = picked.includes(idx);
                  return (
                    <TableRow key={idx} className={cn(!on && "opacity-40")}>
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={!pending}
                          onChange={() =>
                            setPicked(on ? picked.filter((x) => x !== idx) : [...picked, idx].sort((a, b) => a - b))
                          }
                        />
                      </TableCell>
                      <TableCell className="capitalize">{st.action.replace(/_/g, " ")}</TableCell>
                      <TableCell className="font-mono text-xs">{st.sku}</TableCell>
                      <TableCell className="text-right">{st.qty || "—"}</TableCell>
                      <TableCell className="text-sm">{st.vendor_id || "—"}</TableCell>
                      <TableCell className="text-right">{st.value_sgd ? `S$${st.value_sgd.toFixed(2)}` : "—"}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          <p className="text-sm mt-2">
            <strong>Selected: S${selectedTotal.toFixed(2)}</strong>
            {selectedTotal !== (queued.total_sgd ?? 0) && (
              <span className="text-muted-foreground"> of S${(queued.total_sgd ?? 0).toFixed(2)} queued</span>
            )}
          </p>
        </Section>

        {flagSteps.length > 0 && (
          <Section title="Flagged for your review">
            <p className="text-xs text-muted-foreground mb-2">
              The agent could not act on these on its own — read each one and tick "Reviewed" before you can
              approve this run. This does not place an order; it only clears the way to approve the rest.
            </p>
            <div className="space-y-2">
              {flagSteps.map((st, i) => {
                const idx = st.index ?? i;
                const reviewed = reviewedFlags.has(idx);
                return (
                  <div
                    key={idx}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 text-sm",
                      reviewed ? "border-stone-200 bg-stone-50" : "border-amber-300 bg-amber-50",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={reviewed}
                      disabled={!pending}
                      onChange={() => {
                        const next = new Set(reviewedFlags);
                        reviewed ? next.delete(idx) : next.add(idx);
                        setReviewedFlags(next);
                      }}
                    />
                    <div className="flex-1">
                      <div className="font-mono text-xs text-stone-500">{st.sku}</div>
                      <div className="text-stone-700">{st.rationale || "No stocked SKU covers this need."}</div>
                    </div>
                    {!reviewed && pending && (
                      <Badge className="bg-amber-100 text-amber-800 border-amber-200">needs review</Badge>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        <Section title="Adaptations it had to make">
          {adaptations.length === 0 ? (
            <p className="text-sm text-muted-foreground">None — every action succeeded on the first try.</p>
          ) : (
            <div className="space-y-2">
              {moqAdaptations.length > 0 && (
                <details className="rounded-lg border border-stone-200 bg-stone-50 p-3">
                  <summary className="cursor-pointer text-sm font-medium flex items-center gap-2 list-none [&::-webkit-details-marker]:hidden">
                    <ChevronDown className="h-4 w-4 text-stone-500 transition-transform [details[open]_&]:rotate-180" />
                    {moqAdaptations.length} vendor minimum-order retr{moqAdaptations.length > 1 ? "ies" : "y"}{" "}
                    (MOQ_NOT_MET)
                  </summary>
                  <div className="mt-2 space-y-2 pl-6">
                    {moqAdaptations.map((a, i) => (
                      <AdaptationLine key={i} a={a} />
                    ))}
                  </div>
                </details>
              )}
              {otherAdaptations.map((a, i) => (
                <div key={i} className="rounded-lg border border-stone-200 bg-stone-50 p-3">
                  <AdaptationLine a={a} />
                </div>
              ))}
            </div>
          )}
        </Section>

        {run.outcome && <OutcomePanel outcome={run.outcome} />}

        <Section title="Node trace">
          {["seed", "agent", "tools", "finalize"].map((node) => (
            <details key={node} className="mb-1">
              <summary className="cursor-pointer text-sm text-stone-600">{node}</summary>
              <pre className="text-xs whitespace-pre-wrap break-all bg-stone-50 rounded p-2 mt-1">
                {JSON.stringify((s.trace || []).filter((t: any) => t.node === node), null, 2)}
              </pre>
            </details>
          ))}
        </Section>

        <DialogFooter>
          {run.status === "committing" && (
            <Button variant="outline" disabled={busy} onClick={() => onDecide(run.thread_id, run.decision)}>
              <RefreshCw className="h-4 w-4 mr-2" /> Retry interrupted decision
            </Button>
          )}
          {pending && (
            <>
              <Button
                variant="outline"
                disabled={busy}
                className="border-destructive/50 text-destructive hover:bg-destructive hover:text-white"
                onClick={() => onDecide(run.thread_id, "rejected", [])}
              >
                Reject all
              </Button>
              <Button
                disabled={busy || !canApprove}
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
                onClick={approve}
                title={!allFlagsReviewed ? "Review every flagged item first" : undefined}
              >
                {busy
                  ? "Committing…"
                  : !allFlagsReviewed
                    ? `Review ${flagSteps.length - reviewedFlags.size} flagged item(s) to continue`
                    : `Approve ${picked.length + flagSteps.length} of ${steps.length} — S$${selectedTotal.toFixed(2)}`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AdaptationLine({ a }: { a: any }) {
  return (
    <div className="text-sm">
      <div className="font-medium text-stone-800">
        {a.sku ? `${a.sku} — ` : ""}attempt {a.attempt} after {a.error_code}
      </div>
      <div className="text-stone-600">{a.what_changed}</div>
    </div>
  );
}

function OutcomePanel({ outcome }: { outcome: any }) {
  if (outcome.kind === "acquisition_checklist") {
    // A donation-fed charity does not place orders — this must read as an
    // actual acquisition checklist for staff to work from, not a shopping
    // list with vendors and prices (there are none; nothing was purchased).
    return (
      <Section title="Acquisition checklist">
        <p className="text-xs text-muted-foreground mb-2">
          No purchase was made — this charity is donation-fed. Ranked by urgency × days of cover short, for staff
          to action.
        </p>
        {(outcome.items || []).length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing to acquire this run.</p>
        ) : (
          <ul className="space-y-2">
            {outcome.items.map((item: any, i: number) => (
              <li key={i} className="flex items-start gap-3 rounded-lg border border-stone-200 p-3 text-sm">
                <input type="checkbox" className="mt-0.5" aria-label={`Mark ${item.sku} acquired`} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">{item.sku}</span>
                    <Badge variant="outline" className="text-xs">
                      qty {item.qty}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      urgency {item.urgency}
                    </Badge>
                  </div>
                  {item.why && <div className="text-stone-600 mt-0.5">{item.why}</div>}
                </div>
              </li>
            ))}
          </ul>
        )}
        {(outcome.review_flags || []).length > 0 && (
          <p className="text-xs text-muted-foreground mt-2">
            {outcome.review_flags.length} item(s) also flagged for human review — see above.
          </p>
        )}
      </Section>
    );
  }

  if (outcome.kind === "commit_failed") {
    return (
      <Section title="Commit result">
        <Banner tone="err">
          {(outcome.failed_steps || []).length} order(s) could not be committed. Nothing was charged for these
          lines.
        </Banner>
        <ul className="text-sm space-y-1 mt-2">
          {(outcome.failed_steps || []).map((f: any, i: number) => (
            <li key={i}>
              <span className="font-mono text-xs">{f.step?.sku}</span> — {f.error}
            </li>
          ))}
        </ul>
      </Section>
    );
  }

  // purchase_order — a real shopping list makes sense here, this charity is
  // budget-funded and actually spent money.
  return (
    <Section title="Purchase order">
      <p className="text-sm">
        <strong>S${(outcome.total_sgd ?? 0).toFixed(2)}</strong> committed across {(outcome.orders || []).length}{" "}
        order(s).
      </p>
      {(outcome.declined_steps || []).length > 0 && (
        <p className="text-xs text-muted-foreground mt-1">
          {outcome.declined_steps.length} line(s) declined and not ordered.
        </p>
      )}
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-stone-100 pt-4 mt-4 first:border-0 first:mt-0 first:pt-0">
      <h3 className="text-sm font-semibold text-stone-800 mb-2">{title}</h3>
      {children}
    </div>
  );
}

function Banner({ tone, children }: { tone: "err" | "warn"; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-sm flex items-start gap-2",
        tone === "err" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-800",
      )}
    >
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}
