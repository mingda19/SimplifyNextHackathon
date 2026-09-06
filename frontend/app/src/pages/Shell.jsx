import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Banner, Pill } from '../components/ui'

export default function Shell() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [pending, setPending] = useState(0)
  const [fakeServices, setFakeServices] = useState([])

  // The pending-approval count is the one number a charity needs at a glance:
  // it is work the agent has queued and cannot do without a human.
  useEffect(() => {
    let alive = true
    const poll = () => api.runs('pending_approval')
      .then(r => alive && setPending(r.length)).catch(() => {})
    poll()
    const id = setInterval(poll, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // A red "fake mode" banner has to be impossible to miss: the bug this
  // exists to catch is "nobody noticed FAKE_LLM was still on" -- which
  // previously took someone actually reading a log line to find. Both
  // /health endpoints already report fake_llm; surface it here directly.
  useEffect(() => {
    let alive = true
    const poll = () => Promise.allSettled([
      api.feedbackHealth().then(h => ['Feedback extraction', h]),
      api.agentHealth().then(h => ['Agent reasoning', h]),
    ]).then(results => {
      if (!alive) return
      setFakeServices(
        results
          .filter(r => r.status === 'fulfilled' && r.value[1]?.fake_llm)
          .map(r => r.value[0])
      )
    })
    poll()
    const id = setInterval(poll, 15000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const link = ({ isActive }) => 'navlink' + (isActive ? ' active' : '')
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">Pantry<span>.</span></div>
        <NavLink to="/stock" className={link}>Stock</NavLink>
        <NavLink to="/agent" className={link}>
          Agent actions
          {pending > 0 && <Pill kind="warn">{pending}</Pill>}
        </NavLink>
        <NavLink to="/feedback" className={link}>Beneficiary needs</NavLink>
        <NavLink to="/people" className={link}>People &amp; links</NavLink>
        <div className="side-foot">
          <div className="small" style={{ fontWeight: 600 }}>{user?.name}</div>
          <div className="small muted" style={{ marginBottom: 8 }}>{user?.email}</div>
          <button className="btn-sm" style={{ width: '100%' }}
                  onClick={() => { logout(); nav('/login', { replace: true }) }}>
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">
        {fakeServices.length > 0 && (
          <Banner kind="err">
            <strong>FAKE MODE:</strong> {fakeServices.join(' and ')} {fakeServices.length > 1 ? 'are' : 'is'} running
            on canned responses, not real Bedrock calls. Set FAKE_LLM=0 and restart before a real demo or test run.
          </Banner>
        )}
        <Outlet />
      </main>
    </div>
  )
}
