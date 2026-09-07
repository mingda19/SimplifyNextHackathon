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

  const load = () =>
    api
      .runs()
      .then((r) => {
        setRuns(r);
        setErr(null);
      })
      .catch(setErr);
  useEffect(() => {
    load();
    // A run takes tens of seconds; poll so the queue updates without a refresh.
    const id = setInterval(load, 5000);
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

  const decide = async (id, decision, approvedSteps) => {
    setBusy(true);
    try {
      // FIX: Pass a single payload object that exactly matches your api.py schema
      const payload = {
        decision: decision,
        decided_by: user?.email,
        approved_steps: approvedSteps,
      };

      // Update this line to match how your api.js accepts object payloads
      // (If api.decide expects (id, payload))
      const r = await api.decide(id, decision, user?.email, approvedSteps);

      const dec = r.outcome?.declined_steps?.length || 0;
      const res = r.outcome?.feedback_resolved || 0;
      setNote(
        decision === "approved"
          ? `Approved${dec ? ` (${dec} line${dec > 1 ? "s" : ""} declined)` : ""}. ` +
              `${
                r.outcome?.kind === "purchase_order"
                  ? `Committed S$${(r.outcome.total_sgd ?? 0).toFixed(2)}.`
                  : "Checklist issued."
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
        </div>
      </div>

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

  // Everything starts ticked — the agent's plan is the default, and the human
  // subtracts from it rather than assembling it line by line.
  const allIdx = (queued.steps || []).map((st, i) => st.index ?? i);
  const [picked, setPicked] = useState(allIdx);
  useEffect(() => {
    setPicked(allIdx);
  }, [run.thread_id, (queued.steps || []).length]);
  const selectedTotal = (queued.steps || [])
    .filter((st, i) => picked.includes(st.index ?? i))
    .reduce((t, st) => t + (st.value_sgd || 0), 0);

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
          Tick only the lines you want. Unticked lines are not ordered and do
          not close the beneficiary messages behind them.
        </p>
        {(queued.steps || []).length === 0 ? (
          <p className="muted small">Nothing queued.</p>
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
              {queued.steps.map((st, i) => {
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
                    <td className="small">
                      {st.action === "flag_for_human" ? (
                        // A gap means nothing in the catalogue can serve this need.
                        // Ticking it off changes nothing — the fix is to create the
                        // SKU so the agent can order it next run.
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
                      ) : (
                        st.vendor_id || "—"
                      )}
                    </td>
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

        <h3>Adaptations it had to make</h3>
        {adaptations.length === 0 ? (
          <p className="muted small">
            None — validation succeeded on the first try.
          </p>
        ) : (
          adaptations.map((a, i) => (
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
                Attempt {a.attempt} after {a.error_code}
              </div>
              <div className="small">{a.what_changed}</div>
              {a.confidence != null && (
                <div className="muted small">
                  confidence {Math.round(a.confidence * 100)}%
                </div>
              )}
            </div>
          ))
        )}

        <h3>Node trace</h3>
        {["sense", "predict", "act", "adapt", "approval", "commit"].map(
          (node) => (
            <details key={node} style={{ marginBottom: 8 }}>
              <summary>{node}</summary>
              <pre
                className="small"
                style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                {JSON.stringify(
                  (s.trace || []).filter((t) => t.node === node),
                  null,
                  2,
                )}
              </pre>
            </details>
          ),
        )}
        {run.outcome && (
          <details>
            <summary>Outcome</summary>
            <pre className="small" style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(run.outcome, null, 2)}
            </pre>
          </details>
        )}
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
              disabled={busy || picked.length === 0}
              onClick={() => onDecide(run.thread_id, "approved", picked)}
            >
              {busy
                ? "Committing…"
                : `Approve ${picked.length} of ${allIdx.length} — S$${selectedTotal.toFixed(2)}`}
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
