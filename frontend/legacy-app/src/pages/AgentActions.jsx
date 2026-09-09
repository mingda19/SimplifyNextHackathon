import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Banner, Empty, Pill, ServiceDown, Stat } from "../components/ui";
import { ItemEditor } from "./Stock";

const STATUS = {
  running: { kind: "mute", label: "running" },
  committing: { kind: "warn", label: "decision in progress" },
  completed: { kind: "ok", label: "no action needed" },
  pending_approval: { kind: "warn", label: "needs your approval" },
  approved: { kind: "ok", label: "approved" },
  rejected: { kind: "mute", label: "rejected" },
  failed: { kind: "danger", label: "failed" },
};

export default function AgentActions() {
  const { user } = useAuth();
  const [runs, setRuns] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [creatingSku, setCreatingSku] = useState(null);
  const [charityType, setCharityType] = useState("B");
  const [watch, setWatchState] = useState(null);
  const [watchBusy, setWatchBusy] = useState(false);

  const load = () =>
    api
      .runs()
      .then((r) => {
        setRuns(r);
        setErr(null);
      })
      .catch(setErr);

  const loadWatch = () => api.getWatch().then(setWatchState).catch(() => {});

  useEffect(() => {
    load();
    loadWatch();
    // A run takes tens of seconds; poll so the queue (and watch status)
    // updates without a refresh. Watch mode itself polls server-side every
    // 60s -- this is just the UI catching up on what it already decided.
    const id = setInterval(() => {
      load();
      loadWatch();
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const start = async () => {
    setBusy(true);
    setNote("");
    try {
      await api.startRun(charityType);
      setNote("Agent run started — it will appear below when it needs you.");
      load();
    } catch (ex) {
      setNote("");
      setErr(ex);
    } finally {
      setBusy(false);
    }
  };

  const toggleWatch = async () => {
    setWatchBusy(true);
    const active = !watch?.active;
    try {
      const w = await api.setWatch(active, charityType);
      setWatchState(w);
      setNote(
        active
          ? "Agent activated — it will act on its own once 10+ feedback messages arrive or inventory shifts a lot. It checks every minute and switches itself off after 2 quiet checks with nothing to do."
          : "Agent deactivated.",
      );
    } catch (ex) {
      setErr(ex);
    } finally {
      setWatchBusy(false);
    }
  };

  const decide = async (id, decision, approvedSteps) => {
    setBusy(true);
    try {
      const r = await api.decide(id, decision, user?.email, approvedSteps);

      const dec = r.outcome?.declined_steps?.length || 0;
      const res = r.outcome?.feedback_resolved || 0;
      setNote(
        decision === "approved"
          ? `Approved${dec ? ` (${dec} line${dec > 1 ? "s" : ""} declined)` : ""}. ` +
              `${
                r.outcome?.kind === "purchase_order"
                  ? `Committed S$${(r.outcome.total_sgd ?? 0).toFixed(2)}.`
                  : r.outcome?.kind === "acquisition_checklist"
                    ? "Checklist issued."
                    : "No orders were committed — check the failure details."
              }` +
              `${res ? ` ${res} beneficiary message${res > 1 ? "s" : ""} marked resolved.` : ""}`
          : "Rejected — nothing was committed.",
      );
      setOpen(null);
      load();
    } catch (ex) {
      setErr(ex);
    } finally {
      setBusy(false);
    }
  };

  if (err && !runs)
    return (
      <>
        <h1>Agent actions</h1>
        <ServiceDown name="Orchestrator" error={err} />
      </>
    );
  if (!runs)
    return (
      <>
        <h1>Agent actions</h1>
        <Empty>Loading…</Empty>
      </>
    );

  const pending = runs.filter((r) => r.status === "pending_approval");
  const detail = open ? runs.find((r) => r.thread_id === open) : null;

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Agent actions</h1>
          <p className="muted small" style={{ margin: 0 }}>
            The agent senses stock, beneficiary needs and prices, then queues a
            plan. Nothing is committed until you approve it.
          </p>
        </div>
        <div className="row">
          <select
            aria-label="Funding type"
            value={charityType}
            onChange={(e) => setCharityType(e.target.value)}
          >
            <option value="B">Budget funded — purchase orders</option>
            <option value="A">Donation fed — checklist</option>
          </select>
          <button className="btn-primary" onClick={start} disabled={busy}>
            {busy ? "Working…" : "Run agent now"}
          </button>
          <button
            className={watch?.active ? "btn-primary" : ""}
            onClick={toggleWatch}
            disabled={watchBusy}
            title={
              watch?.active
                ? "Click to deactivate"
                : "Agent watches on its own for 10+ new feedback messages or a big inventory shift, checking every minute"
            }
          >
            {watchBusy ? "Working…" : watch?.active ? "Agent active ●" : "Activate agent"}
          </button>
        </div>
      </div>

      {watch?.active && (
        <div className="banner banner-ok" style={{ marginBottom: 14 }}>
          Watching for 10+ new feedback messages or a big inventory shift — checking every minute.
          {watch.last_poll_at && ` Last checked ${new Date(watch.last_poll_at).toLocaleTimeString()}.`}
          {watch.last_trigger_at && ` Last acted ${new Date(watch.last_trigger_at).toLocaleTimeString()}.`}
          {" "}
          Switches off on its own after {watch.quiet_cycles ?? 0}/2 quiet checks with nothing to do.
        </div>
      )}

      <Banner kind="ok">{note}</Banner>
      {err && <ServiceDown name="Orchestrator" error={err} />}

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat
          n={pending.length}
          l="awaiting approval"
          kind={pending.length ? "warn" : undefined}
        />
        <Stat
          n={runs.filter((r) => r.status === "approved").length}
          l="approved"
        />
        <Stat
          n={runs.filter((r) => r.status === "rejected").length}
          l="rejected"
        />
        <Stat
          n={runs.filter((r) => r.status === "failed").length}
          l="failed"
          kind={runs.some((r) => r.status === "failed") ? "danger" : undefined}
        />
      </div>

      {runs.length === 0 ? (
        <Empty>
          No agent runs yet. Use <strong>Run agent now</strong> to start one.
        </Empty>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>What it wants to do</th>
                <th className="num">Value</th>
                <th>Started</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const s = STATUS[r.status] || STATUS.running;
                const p = r.summary?.predicted;
                return (
                  <tr key={r.thread_id}>
                    <td className="mono small">{r.thread_id}</td>
                    <td>
                      <Pill kind={s.kind}>{s.label}</Pill>
                    </td>
                    <td>
                      {r.error ? (
                        <span className="muted small">
                          {r.error.slice(0, 70)}
                        </span>
                      ) : p?.stockout_sku ? (
                        <>
                          Restock <strong>{p.stockout_sku}</strong>
                          <span className="muted small">
                            {" "}
                            — fails in {p.days_until_failure}d
                          </span>
                        </>
                      ) : (
                        <span className="muted small">—</span>
                      )}
                    </td>
                    <td className="num">
                      {r.summary?.queued?.total_sgd
                        ? `S$${r.summary.queued.total_sgd}`
                        : "—"}
                    </td>
                    <td className="muted small">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {r.summary && (
                        <button
                          className="btn-sm"
                          onClick={() => setOpen(r.thread_id)}
                        >
                          {r.status === "pending_approval" ? "Review" : "View"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <RunDetail
          run={detail}
          busy={busy}
          onClose={() => setOpen(null)}
          onDecide={decide}
          onCreateSku={setCreatingSku}
        />
      )}
      {creatingSku && (
        <ItemEditor
          item={creatingSku}
          onClose={() => setCreatingSku(null)}
          onSaved={(m) => {
            setCreatingSku(null);
            setNote(m + " The agent can order it on the next run.");
          }}
        />
      )}
    </>
  );
}

// The four panels the guardrail node emits. `adaptations` gets the most space
// on purpose: it is the only place you can see the agent hit a wall and reason
// its way around it, which is the difference between a workflow and an agent.
function RunDetail({ run, busy, onClose, onDecide, onCreateSku }) {
  const s = run.summary || {};
  const {
    sensed = {},
    predicted = {},
    queued = {},
    adaptations = [],
    guardrails = {},
  } = s;
  const pending = run.status === "pending_approval";
  const legacy = s.approval_version !== 2;

  const steps = queued.steps || [];
  const actionableSteps = steps.filter((st) => st.action !== "flag_for_human");
  const flagSteps = steps.filter((st) => st.action === "flag_for_human");
  const actionableIdx = actionableSteps.map((st, i) => st.index ?? i);
  const flagIdx = flagSteps.map((st, i) => st.index ?? i);

  // 2. Logic to determine historical checkbox state based on run status and database outcome
  const getHistoricalSelection = () => {
    if (run.status === "pending_approval" || run.status === "committing") {
      return actionableIdx;
    }
    if (run.status === "rejected") {
      return [];
    }
    if (run.outcome?.declined_steps) {
      const declinedSkus = run.outcome.declined_steps.map((d) => d.sku);
      return actionableSteps
        .map((st, i) => ({ idx: st.index ?? i, sku: st.sku }))
        .filter((st) => !declinedSkus.includes(st.sku))
        .map((st) => st.idx);
    }
    return actionableIdx;
  };

  const [picked, setPicked] = useState(getHistoricalSelection());
  // Flags need an explicit review, separate from "include in this order" --
  // previously they were just another pre-checked row in `picked`, so
  // clicking Approve required no attention to them at all. Unchecked by
  // default; historical (already-decided) runs don't need this gate any
  // more, so they render as already-reviewed.
  const [reviewedFlags, setReviewedFlags] = useState(
    pending ? new Set() : new Set(flagIdx),
  );

  useEffect(() => {
    setPicked(getHistoricalSelection());
    setReviewedFlags(run.status === "pending_approval" ? new Set() : new Set(flagIdx));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.thread_id, steps.length, run.status, run.outcome]);

  const selectedTotal = actionableSteps
    .filter((st, i) => picked.includes(st.index ?? i))
    .reduce((t, st) => t + (st.value_sgd || 0), 0);

  const allFlagsReviewed = flagIdx.every((idx) => reviewedFlags.has(idx));
  const canApprove =
    pending && (picked.length > 0 || flagIdx.length > 0) && allFlagsReviewed;

  const approve = () =>
    onDecide(run.thread_id, "approved", [...picked, ...flagIdx].sort((a, b) => a - b));

  const moqAdaptations = adaptations.filter((a) => a.error_code === "MOQ_NOT_MET");
  const otherAdaptations = adaptations.filter((a) => a.error_code !== "MOQ_NOT_MET");

  return (
    <div className="modal-back" onClick={onClose}>
      <div
        className="modal"
        style={{ maxWidth: 720 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pagehead">
          <div>
            <h2 style={{ marginBottom: 2 }}>Agent plan</h2>
            <span className="mono small muted">{run.thread_id}</span>
          </div>
          <button className="btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        {guardrails.halt_reason && (
          <Banner kind="err">{guardrails.halt_reason}</Banner>
        )}
        {pending && legacy && (
          <Banner kind="err">
            This is an older plan. Review existing orders and start a new run
            before approving.
          </Banner>
        )}
        {run.error && <Banner kind="err">{run.error}</Banner>}
        {guardrails.exceeds_monthly_budget && (
          <Banner kind="err">
            This plan exceeds the monthly budget and needs revision.
          </Banner>
        )}
        {guardrails.exceeds_single_order_cap && (
          <div className="banner banner-warn">
            This order exceeds the single-order cap of S$
            {guardrails.baselines?.max_single_order_sgd}.
          </div>
        )}

        <h3>What it sensed</h3>
        <ul className="small" style={{ marginTop: 4 }}>
          <li>
            {(sensed.below_reorder || []).length} item(s) below reorder point
          </li>
          <li>{(sensed.expiring_soon || []).length} lot(s) expiring soon</li>
          {(sensed.top_unmet_needs || []).map((n, i) => (
            <li key={i}>
              “{n.need}” — {n.frequency} beneficiary/ies, urgency {n.urgency}
              {n.gap && (
                <>
                  {" "}
                  <Pill kind="danger">no stocked SKU</Pill>
                </>
              )}
            </li>
          ))}
          {(sensed.price_signals || []).map((p, i) => (
            <li key={`p${i}`}>
              {p.series} prices {p.direction} ({p.pct_change_3m}% / 3mo) →{" "}
              <strong>{p.recommendation}</strong>
              <span className="muted">
                {" "}
                · {Math.round((p.confidence || 0) * 100)}% confidence · data lag{" "}
                {p.data_lag_months}mo
              </span>
            </li>
          ))}
          {(sensed.price_signals || []).length === 0 && (
            <li className="muted">
              No actionable price signal — everything at risk was NEUTRAL or has
              no forecast (perishables are excluded from the price model).
            </li>
          )}
          {(sensed.unavailable_services || []).length > 0 && (
            <li className="muted">
              Reasoned without: {sensed.unavailable_services.join(", ")}
            </li>
          )}
        </ul>

        <h3>What it predicts</h3>
        <p className="small" style={{ marginTop: 4 }}>
          {predicted.reasoning}
        </p>

        <h3>What it has queued</h3>
        <p className="muted small" style={{ marginTop: -4 }}>
          {pending
            ? "Tick only the lines you want. Unticked lines are not ordered and do not close the beneficiary messages behind them."
            : "Unticked lines were rejected and not ordered."}
        </p>
        {actionableSteps.length === 0 ? (
          <p className="muted small">Nothing queued for purchase.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 34 }}></th>
                <th>Action</th>
                <th>Item</th>
                <th className="num">Qty</th>
                <th>Vendor</th>
                <th className="num">Value</th>
              </tr>
            </thead>
            <tbody>
              {actionableSteps.map((st, i) => {
                const idx = st.index ?? i;
                const on = picked.includes(idx);
                return (
                  <tr key={idx} style={{ opacity: on ? 1 : 0.45 }}>
                    <td>
                      <input
                        type="checkbox"
                        style={{ width: 18 }}
                        checked={on}
                        disabled={!pending}
                        onChange={() =>
                          setPicked(
                            on
                              ? picked.filter((x) => x !== idx)
                              : [...picked, idx].sort((a, b) => a - b),
                          )
                        }
                      />
                    </td>
                    <td>{st.action.replace(/_/g, " ")}</td>
                    <td className="mono small">{st.sku}</td>
                    <td className="num">{st.qty || "—"}</td>
                    <td className="small">{st.vendor_id || "—"}</td>
                    <td className="num">
                      {st.value_sgd ? `S$${st.value_sgd.toFixed(2)}` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="small" style={{ marginTop: 8 }}>
          <strong>Selected: S${selectedTotal.toFixed(2)}</strong>
          {selectedTotal !== (queued.total_sgd ?? 0) && (
            <span className="muted">
              {" "}
              of S${(queued.total_sgd ?? 0).toFixed(2)} queued
            </span>
          )}
        </p>

        {flagSteps.length > 0 && (
          <>
            <h3>Flagged for your review</h3>
            <p className="muted small" style={{ marginTop: -4 }}>
              The agent could not act on these on its own. Read each one and
              tick <strong>Reviewed</strong> before you can approve this run
              — ticking does not place an order, it only clears the way to
              approve the rest.
            </p>
            {flagSteps.map((st, i) => {
              const idx = st.index ?? i;
              const reviewed = reviewedFlags.has(idx);
              return (
                <div
                  key={idx}
                  className="card"
                  style={{
                    marginBottom: 8,
                    borderColor: reviewed ? undefined : "#eddcb4",
                    background: reviewed ? undefined : "var(--warn-soft)",
                  }}
                >
                  <div className="row" style={{ alignItems: "flex-start" }}>
                    <input
                      type="checkbox"
                      style={{ width: 18, marginTop: 3 }}
                      checked={reviewed}
                      disabled={!pending}
                      onChange={() => {
                        const next = new Set(reviewedFlags);
                        reviewed ? next.delete(idx) : next.add(idx);
                        setReviewedFlags(next);
                      }}
                    />
                    <div style={{ flex: 1 }}>
                      <div className="mono small muted">{st.sku}</div>
                      <div className="small">
                        {st.rationale || "No stocked SKU covers this need."}
                      </div>
                    </div>
                    <button
                      className="btn-sm btn-primary"
                      type="button"
                      onClick={() =>
                        onCreateSku({
                          __prefill: true,
                          sku: st.sku,
                          name: (st.rationale || st.sku).slice(0, 60),
                          category: "UNCATEGORISED",
                        })
                      }
                    >
                      Create this SKU
                    </button>
                  </div>
                  {!reviewed && pending && (
                    <div className="small" style={{ marginTop: 6 }}>
                      <Pill kind="warn">needs review</Pill>
                    </div>
                  )}
                </div>
              );
            })}
          </>
        )}

        <h3>Adaptations it had to make</h3>
        {adaptations.length === 0 ? (
          <p className="muted small">
            None — validation succeeded on the first try.
          </p>
        ) : (
          <>
            {moqAdaptations.length > 0 && (
              <details className="card" style={{ marginBottom: 8, padding: "10px 14px" }}>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                  {moqAdaptations.length} vendor minimum-order retr
                  {moqAdaptations.length > 1 ? "ies" : "y"} (MOQ_NOT_MET)
                </summary>
                <div style={{ marginTop: 8 }}>
                  {moqAdaptations.map((a, i) => (
                    <div
                      key={i}
                      className="small"
                      style={{ marginBottom: i < moqAdaptations.length - 1 ? 8 : 0 }}
                    >
                      <div style={{ fontWeight: 600 }}>
                        {a.sku ? `${a.sku} — ` : ""}attempt {a.attempt}
                      </div>
                      <div>{a.what_changed}</div>
                    </div>
                  ))}
                </div>
              </details>
            )}
            {otherAdaptations.map((a, i) => (
              <div
                key={i}
                className="card"
                style={{
                  background: "var(--accent-soft)",
                  borderColor: "#bcd9c9",
                  marginBottom: 8,
                }}
              >
                <div className="small" style={{ fontWeight: 600 }}>
                  {a.sku ? `${a.sku} — ` : ""}attempt {a.attempt} after {a.error_code}
                </div>
                <div className="small">{a.what_changed}</div>
                {a.confidence != null && (
                  <div className="muted small">
                    confidence {Math.round(a.confidence * 100)}%
                  </div>
                )}
              </div>
            ))}
          </>
        )}

        <h3>Node trace</h3>
        {["seed", "agent", "tools", "finalize"].map((node) => (
          <details key={node} style={{ marginBottom: 8 }}>
            <summary>{node}</summary>
            <pre
              className="small"
              style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
            >
              {JSON.stringify(
                (s.trace || s.attempts || []).filter((t) => t.node === node),
                null,
                2,
              )}
            </pre>
          </details>
        ))}
        {run.outcome && <OutcomePanel outcome={run.outcome} />}
        {run.status === "committing" && (
          <button
            disabled={busy}
            onClick={() => onDecide(run.thread_id, run.decision)}
          >
            Retry interrupted decision
          </button>
        )}
        {pending ? (
          <div
            className="row"
            style={{ justifyContent: "flex-end", marginTop: 18 }}
          >
            <button
              className="btn-danger"
              disabled={busy}
              onClick={() => onDecide(run.thread_id, "rejected", [])}
            >
              Reject all
            </button>
            <button
              className="btn-primary"
              disabled={busy || !canApprove}
              onClick={approve}
              title={!allFlagsReviewed ? "Review every flagged item first" : undefined}
            >
              {busy
                ? "Committing…"
                : !allFlagsReviewed
                  ? `Review ${flagIdx.length - reviewedFlags.size} flagged item(s) to continue`
                  : `Approve ${picked.length + flagIdx.length} of ${actionableIdx.length + flagIdx.length} — S$${selectedTotal.toFixed(2)}`}
            </button>
          </div>
        ) : (
          <p className="muted small" style={{ marginTop: 16 }}>
            {run.status === "approved"
              ? `Approved by ${run.decided_by || "someone"}.`
              : run.status === "rejected"
                ? "Plan rejected."
                : ""}
          </p>
        )}
      </div>
    </div>
  );
}

// A donation-fed charity (`kind: "acquisition_checklist"`) placed no order —
// this must read as a checklist for staff to work from, not a purchase
// summary with vendors and dollar figures that were never spent.
function OutcomePanel({ outcome }) {
  if (outcome.kind === "acquisition_checklist") {
    return (
      <>
        <h3>Acquisition checklist</h3>
        <p className="muted small" style={{ marginTop: -4 }}>
          No purchase was made — this charity is donation-fed. Ranked by
          urgency × days of cover short, for staff to action.
        </p>
        {(outcome.items || []).length === 0 ? (
          <p className="muted small">Nothing to acquire this run.</p>
        ) : (
          (outcome.items || []).map((item, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-start", marginBottom: 8 }}>
              <input type="checkbox" style={{ width: 18, marginTop: 3 }} aria-label={`Mark ${item.sku} acquired`} />
              <div style={{ flex: 1 }}>
                <div className="small">
                  <span className="mono">{item.sku}</span>{" "}
                  <Pill kind="mute">qty {item.qty}</Pill>{" "}
                  <Pill kind="mute">urgency {item.urgency}</Pill>
                </div>
                {item.why && <div className="muted small">{item.why}</div>}
              </div>
            </div>
          ))
        )}
        {(outcome.review_flags || []).length > 0 && (
          <p className="muted small">
            {outcome.review_flags.length} item(s) also flagged for human review — see above.
          </p>
        )}
      </>
    );
  }

  if (outcome.kind === "commit_failed") {
    return (
      <>
        <h3>Commit result</h3>
        <Banner kind="err">
          {(outcome.failed_steps || []).length} order(s) could not be committed. Nothing was charged for these lines.
        </Banner>
        {(outcome.failed_steps || []).map((f, i) => (
          <div key={i} className="small" style={{ marginBottom: 4 }}>
            <span className="mono">{f.step?.sku}</span> — {f.error}
          </div>
        ))}
      </>
    );
  }

  return (
    <>
      <h3>Purchase order</h3>
      <p className="small">
        <strong>S${(outcome.total_sgd ?? 0).toFixed(2)}</strong> committed across{" "}
        {(outcome.orders || []).length} order(s).
      </p>
      {(outcome.declined_steps || []).length > 0 && (
        <p className="muted small">
          {outcome.declined_steps.length} line(s) declined and not ordered.
        </p>
      )}
    </>
  );
}
