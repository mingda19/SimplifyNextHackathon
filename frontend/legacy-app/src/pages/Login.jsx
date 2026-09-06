import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Banner } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const u = await login(email, password)
      nav(u.role === 'charity' ? '/stock' : '/request', { replace: true })
    } catch (ex) {
      setErr(ex.offline ? 'The accounts service is not running. Start it with ./scripts/run_stack.sh' : ex.message)
    } finally { setBusy(false) }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand" style={{ padding: 0, marginBottom: 6 }}>Pantry<span>.</span></div>
        <p className="muted small" style={{ marginTop: 0 }}>Charity supply operations</p>
        <Banner>{err}</Banner>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="username" required
                 value={email} onChange={e => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw">Password</label>
          <input id="pw" type="password" autoComplete="current-password" required
                 value={password} onChange={e => setPassword(e.target.value)} />
        </div>
        <button className="btn-primary" style={{ width: '100%' }} disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="small muted" style={{ marginTop: 16, marginBottom: 0 }}>
          New charity? <Link to="/signup">Create an account</Link><br />
          Beneficiaries do not need an account — ask your charity for a request link.
        </p>
      </form>
    </div>
  )
}
