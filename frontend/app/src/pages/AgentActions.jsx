import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Banner, Empty, Pill, ServiceDown, Stat } from '../components/ui'

const STATUS = {
  running:          { kind: 'mute',   label: 'running' },
  committing:       { kind: 'warn',   label: 'decision in progress' },
  completed:        { kind: 'ok',     label: 'no action needed' },
  pending_approval: { kind: 'warn',   label: 'needs your approval' },
  approved:         { kind: 'ok',     label: 'approved' },
  rejected:         { kind: 'mute',   label: 'rejected' },
  failed:           { kind: 'danger', label: 'failed' },
}

export default function AgentActions() {
  const { user } = useAuth()
  const [runs, setRuns] = useState(null)
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [charityType, setCharityType] = useState('B')

  const load = () => api.runs().then(r => { setRuns(r); setErr(null) }).catch(setErr)
  useEffect(() => {
    load()
    // A run takes tens of seconds; poll so the queue updates without a refresh.
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  const start = async () => {
    setBusy(true); setNote('')
    try { await api.startRun(charityType); setNote('Agent run started — it will appear below when it needs you.'); load() }
    catch (ex) { setNote(''); setErr(ex) } finally { setBusy(false) }
  }

  const decide = async (id, decision) => {
    setBusy(true)
    try {
      const r = await api.decide(id, decision, user?.email)
      setNote(r.status === 'failed' ? 'Commit stopped. Open the run to review any completed actions and the failure.' : decision === 'approved'
        ? `Approved. ${r.outcome?.kind === 'purchase_order' ? `Order committed, S$${r.outcome.total_sgd}.` : 'Checklist issued.'}`
        : 'Plan rejected.')
      setOpen(null); load()
    } catch (ex) { setErr(ex) } finally { setBusy(false) }
  }

  if (err && !runs) return <><h1>Agent actions</h1><ServiceDown name="Orchestrator" error={err} /></>
  if (!runs) return <><h1>Agent actions</h1><Empty>Loading…</Empty></>

  const pending = runs.filter(r => r.status === 'pending_approval')
  const detail = open ? runs.find(r => r.thread_id === open) : null

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Agent actions</h1>
          <p className="muted small" style={{ margin: 0 }}>
            The agent senses stock, beneficiary needs and prices, then queues a plan.
            Nothing is committed until you approve it.
          </p>
        </div>
        <div className="row">
        <select aria-label="Funding type" value={charityType} onChange={e => setCharityType(e.target.value)}>
          <option value="B">Budget funded — purchase orders</option>
          <option value="A">Donation fed — checklist</option>
        </select>
        <button className="btn-primary" onClick={start} disabled={busy}>
          {busy ? 'Working…' : 'Run agent now'}
        </button>
        </div>
      </div>

      <Banner kind="ok">{note}</Banner>
      {err && <ServiceDown name="Orchestrator" error={err} />}

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat n={pending.length} l="awaiting approval" kind={pending.length ? 'warn' : undefined} />
        <Stat n={runs.filter(r => r.status === 'approved').length} l="approved" />
        <Stat n={runs.filter(r => r.status === 'rejected').length} l="rejected" />
        <Stat n={runs.filter(r => r.status === 'failed').length} l="failed"
              kind={runs.some(r => r.status === 'failed') ? 'danger' : undefined} />
      </div>

      {runs.length === 0 ? (
        <Empty>No agent runs yet. Use <strong>Run agent now</strong> to start one.</Empty>
      ) : (
        <div className="card">
          <table>
            <thead><tr>
              <th>Run</th><th>Status</th><th>What it wants to do</th>
              <th className="num">Value</th><th>Started</th><th></th>
            </tr></thead>
            <tbody>
              {runs.map(r => {
                const s = STATUS[r.status] || STATUS.running
                const p = r.summary?.predicted
                return (
                  <tr key={r.thread_id}>
                    <td className="mono small">{r.thread_id}</td>
                    <td><Pill kind={s.kind}>{s.label}</Pill></td>
                    <td>{r.error ? <span className="muted small">{r.error.slice(0, 70)}</span>
                      : p?.stockout_sku ? <>Restock <strong>{p.stockout_sku}</strong>
                        <span className="muted small"> — fails in {p.days_until_failure}d</span></>
                      : <span className="muted small">—</span>}</td>
                    <td className="num">{r.summary?.queued?.total_sgd
                      ? `S$${r.summary.queued.total_sgd}` : '—'}</td>
                    <td className="muted small">{new Date(r.created_at).toLocaleString()}</td>
                    <td style={{ textAlign: 'right' }}>
                      {r.summary && <button className="btn-sm" onClick={() => setOpen(r.thread_id)}>
                        {r.status === 'pending_approval' ? 'Review' : 'View'}</button>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {detail && <RunDetail run={detail} busy={busy} onClose={() => setOpen(null)} onDecide={decide} />}
    </>
  )
}

// The four panels the guardrail node emits. `adaptations` gets the most space
// on purpose: it is the only place you can see the agent hit a wall and reason
// its way around it, which is the difference between a workflow and an agent.
function RunDetail({ run, busy, onClose, onDecide }) {
  const s = run.summary || {}
  const { sensed = {}, predicted = {}, queued = {}, adaptations = [], guardrails = {} } = s
  const pending = run.status === 'pending_approval'
  const legacy = s.approval_version !== 2

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <div className="pagehead">
          <div>
            <h2 style={{ marginBottom: 2 }}>Agent plan</h2>
            <span className="mono small muted">{run.thread_id}</span>
          </div>
          <button className="btn-sm" onClick={onClose}>Close</button>
        </div>

        {guardrails.halt_reason && <Banner kind="err">{guardrails.halt_reason}</Banner>}
        {pending && legacy && <Banner kind="err">This is an older plan. Review existing orders and start a new run before approving.</Banner>}
        {run.error && <Banner kind="err">{run.error}</Banner>}
        {guardrails.exceeds_monthly_budget && <Banner kind="err">This plan exceeds the monthly budget and needs revision.</Banner>}
        {guardrails.exceeds_single_order_cap && (
          <div className="banner banner-warn">
            This order exceeds the single-order cap of S${guardrails.baselines?.max_single_order_sgd}.
          </div>
        )}

        <h3>What it sensed</h3>
        <ul className="small" style={{ marginTop: 4 }}>
          <li>{(sensed.below_reorder || []).length} item(s) below reorder point</li>
          <li>{(sensed.expiring_soon || []).length} lot(s) expiring soon</li>
          {(sensed.top_unmet_needs || []).map((n, i) => (
            <li key={i}>
              “{n.need}” — {n.frequency} beneficiary/ies, urgency {n.urgency}
              {n.gap && <> <Pill kind="danger">no stocked SKU</Pill></>}
            </li>
          ))}
          {sensed.price_signal?.series && (
            <li>{sensed.price_signal.series} prices {sensed.price_signal.direction}
              {' '}({sensed.price_signal.pct_change_3m}% / 3mo) → <strong>{sensed.price_signal.recommendation}</strong>
              <span className="muted"> · data lag {sensed.price_signal.data_lag_months}mo</span></li>
          )}
          {(sensed.unavailable_services || []).length > 0 && (
            <li className="muted">Reasoned without: {sensed.unavailable_services.join(', ')}</li>
          )}
        </ul>

        <h3>What it predicts</h3>
        <p className="small" style={{ marginTop: 4 }}>{predicted.reasoning}</p>

        <h3>What it has queued</h3>
        {(queued.steps || []).length === 0 ? <p className="muted small">Nothing queued.</p> : (
          <table><thead><tr><th>Action</th><th>Item</th><th className="num">Qty</th><th>Vendor</th></tr></thead>
            <tbody>{queued.steps.map((st, i) => (
              <tr key={i}>
                <td>{st.action.replace(/_/g, ' ')}</td>
                <td className="mono small">{st.sku}</td>
                <td className="num">{st.qty || '—'}</td>
                <td className="small">{st.vendor_id || '—'}</td>
              </tr>))}
            </tbody></table>
        )}
        <p className="small" style={{ marginTop: 8 }}><strong>Total: S${queued.total_sgd ?? 0}</strong></p>

        <h3>Adaptations it had to make</h3>
        {adaptations.length === 0 ? (
          <p className="muted small">None — validation succeeded on the first try.</p>
        ) : adaptations.map((a, i) => (
          <div key={i} className="card" style={{ background: 'var(--accent-soft)', borderColor: '#bcd9c9', marginBottom: 8 }}>
            <div className="small" style={{ fontWeight: 600 }}>
              Attempt {a.attempt} after {a.error_code}
            </div>
            <div className="small">{a.what_changed}</div>
            {a.confidence != null && <div className="muted small">confidence {Math.round(a.confidence * 100)}%</div>}
          </div>
        ))}

        <h3>Node trace</h3>
        {['sense', 'predict', 'act', 'adapt', 'approval', 'commit'].map(node => (
          <details key={node} style={{ marginBottom: 8 }}>
            <summary>{node}</summary>
            <pre className="small" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {JSON.stringify((s.trace || []).filter(t => t.node === node), null, 2)}
            </pre>
          </details>
        ))}
        {run.outcome && <details><summary>Outcome</summary>
          <pre className="small" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(run.outcome, null, 2)}</pre>
        </details>}
        {run.status === 'committing' && <button disabled={busy}
          onClick={() => onDecide(run.thread_id, run.decision)}>Retry interrupted decision</button>}
        {pending ? (
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 18 }}>
            <button className="btn-danger" disabled={busy}
                    onClick={() => onDecide(run.thread_id, 'rejected')}>Reject</button>
            <button className="btn-primary" disabled={busy || legacy || !!guardrails.halt_reason || guardrails.exceeds_monthly_budget}
                    onClick={() => onDecide(run.thread_id, 'approved')}>
              {busy ? 'Committing…' : run.charity_type === 'A' ? 'Approve — issue checklist' : `Approve — commit S$${queued.total_sgd ?? 0}`}
            </button>
          </div>
        ) : (
          <p className="muted small" style={{ marginTop: 16 }}>
            {run.status === 'approved' ? `Approved by ${run.decided_by || 'someone'}.`
              : run.status === 'rejected' ? 'Plan rejected.' : ''}
          </p>
        )}
      </div>
    </div>
  )
}
