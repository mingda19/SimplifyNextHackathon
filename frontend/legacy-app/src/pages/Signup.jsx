import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Banner } from '../components/ui'

// The rule list is fetched from the auth service rather than duplicated here,
// so what the user is told can never drift from what the server enforces.
const CHECKS = {
  'at least 10 characters': p => p.length >= 10,
  'an uppercase letter': p => /[A-Z]/.test(p),
  'a lowercase letter': p => /[a-z]/.test(p),
  'a number': p => /\d/.test(p),
}

export default function Signup() {
  const { signup } = useAuth()
  const nav = useNavigate()
  const [form, setForm] = useState({ display_name: '', email: '', password: '' })
  const [rules, setRules] = useState([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.passwordPolicy().then(r => setRules(r.rules)).catch(() => {}) }, [])
  const set = k => e => setForm({ ...form, [k]: e.target.value })
  const allMet = rules.length > 0 && rules.every(r => CHECKS[r]?.(form.password))

  const submit = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    try { await signup({ ...form, role: 'charity' }); nav('/stock', { replace: true }) }
    catch (ex) { setErr(ex.offline ? 'The accounts service is not running.' : ex.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>Create a charity account</h1>
        <p className="muted small" style={{ marginTop: -4 }}>
          This account manages stock, approves agent actions, and invites beneficiaries.
        </p>
        <Banner>{err}</Banner>
        <div className="field">
          <label htmlFor="n">Charity name</label>
          <input id="n" required value={form.display_name} onChange={set('display_name')} />
        </div>
        <div className="field">
          <label htmlFor="e">Email</label>
          <input id="e" type="email" autoComplete="username" required
                 value={form.email} onChange={set('email')} />
        </div>
        <div className="field">
          <label htmlFor="p">Password</label>
          <input id="p" type="password" autoComplete="new-password" required
                 value={form.password} onChange={set('password')} />
          <ul className="rules">
            {rules.map(r => (
              <li key={r} className={CHECKS[r]?.(form.password) ? 'met' : ''}>{r}</li>
            ))}
          </ul>
        </div>
        <button className="btn-primary" style={{ width: '100%' }} disabled={busy || !allMet}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
        <p className="small muted" style={{ marginTop: 16, marginBottom: 0 }}>
          Already have one? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  )
}
