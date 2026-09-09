import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Banner } from '../components/ui'

// Same pattern as Signup.jsx: the rule list is fetched from the auth service
// rather than duplicated here, so what the user is told can never drift from
// what the server enforces.
const CHECKS = {
  'at least 10 characters': p => p.length >= 10,
  'an uppercase letter': p => /[A-Z]/.test(p),
  'a lowercase letter': p => /[a-z]/.test(p),
  'a number': p => /\d/.test(p),
}

export default function Settings() {
  const { user } = useAuth()
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Settings</h1>
          <p className="muted small" style={{ margin: 0 }}>
            Signed in as {user?.name} ({user?.email}).
          </p>
        </div>
      </div>
      <div className="grid g2">
        <BudgetCard />
        <PasswordCard />
      </div>
    </>
  )
}

function BudgetCard() {
  const [value, setValue] = useState('')
  const [saved, setSaved] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getSettings()
      .then(s => { setValue(s.monthly_budget_sgd); setSaved(s) })
      .catch(ex => setErr(ex.offline ? 'The inventory service is not running.' : ex.message))
      .finally(() => setLoading(false))
  }, [])

  const submit = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const n = Number(value)
      if (!Number.isFinite(n) || n <= 0) throw new Error('Enter a positive amount.')
      const s = await api.updateSettings(n)
      setSaved(s)
      setValue(s.monthly_budget_sgd)
    } catch (ex) {
      setErr(ex.offline ? 'The inventory service is not running.' : ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3 style={{ marginTop: 0 }}>Monthly procurement budget</h3>
      <p className="muted small">
        The agent cannot place an order that would push this month's total spend
        past this amount — enforced by the inventory service at commit time, not
        just shown here for reference.
      </p>
      <Banner kind="err">{err}</Banner>
      <div className="field">
        <label htmlFor="budget">S$ per month</label>
        <input
          id="budget"
          type="number"
          min="1"
          step="0.01"
          disabled={loading}
          required
          value={value}
          onChange={e => setValue(e.target.value)}
        />
      </div>
      <button className="btn-primary" disabled={busy || loading}>
        {busy ? 'Saving…' : 'Save budget'}
      </button>
      {saved?.updated_at && (
        <p className="muted small" style={{ marginTop: 10, marginBottom: 0 }}>
          Last changed {new Date(saved.updated_at).toLocaleString()}
          {saved.updated_by ? ` by ${saved.updated_by}` : ''}.
        </p>
      )}
    </form>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [rules, setRules] = useState([])
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.passwordPolicy().then(r => setRules(r.rules)).catch(() => {}) }, [])

  const allMet = rules.length > 0 && rules.every(r => CHECKS[r]?.(next))
  const matches = next.length > 0 && next === confirm

  const submit = async e => {
    e.preventDefault(); setErr(''); setOk(''); setBusy(true)
    try {
      if (next !== confirm) throw new Error('New password and confirmation do not match.')
      await api.changePassword(current, next)
      setOk('Password changed.')
      setCurrent(''); setNext(''); setConfirm('')
    } catch (ex) {
      setErr(ex.offline ? 'The accounts service is not running.' : ex.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h3 style={{ marginTop: 0 }}>Change password</h3>
      <Banner kind="err">{err}</Banner>
      <Banner kind="ok">{ok}</Banner>
      <div className="field">
        <label htmlFor="cur">Current password</label>
        <input id="cur" type="password" autoComplete="current-password" required
               value={current} onChange={e => setCurrent(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="new">New password</label>
        <input id="new" type="password" autoComplete="new-password" required
               value={next} onChange={e => setNext(e.target.value)} />
        <ul className="rules">
          {rules.map(r => (
            <li key={r} className={CHECKS[r]?.(next) ? 'met' : ''}>{r}</li>
          ))}
        </ul>
      </div>
      <div className="field">
        <label htmlFor="confirm">Confirm new password</label>
        <input id="confirm" type="password" autoComplete="new-password" required
               value={confirm} onChange={e => setConfirm(e.target.value)} />
        {confirm.length > 0 && !matches && (
          <p className="small" style={{ color: 'var(--danger)', marginTop: 4 }}>
            Does not match the new password.
          </p>
        )}
      </div>
      <button className="btn-primary" disabled={busy || !allMet || !matches}>
        {busy ? 'Changing…' : 'Change password'}
      </button>
    </form>
  )
}
