import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Pill } from '../components/ui'

export default function Shell() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  const [pending, setPending] = useState(0)
  const [openOrders, setOpenOrders] = useState(0)

  // The pending-approval count is the one number a charity needs at a glance:
  // it is work the agent has queued and cannot do without a human.
  useEffect(() => {
    let alive = true
    const poll = () => {
      api.runs('pending_approval').then(r => alive && setPending(r.length)).catch(() => {})
      api.orders('PLACED').then(r => alive && setOpenOrders(r.length)).catch(() => {})
    }
    poll()
    const id = setInterval(poll, 8000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const link = ({ isActive }) => 'navlink' + (isActive ? ' active' : '')
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">Pantry<span>.</span></div>
        <NavLink to="/stock" className={link}>Stock</NavLink>
        <NavLink to="/orders" className={link}>
          Incoming orders
          {openOrders > 0 && <Pill kind="ok">{openOrders}</Pill>}
        </NavLink>
        <NavLink to="/agent" className={link}>
          Agent actions
          {pending > 0 && <Pill kind="warn">{pending}</Pill>}
        </NavLink>
        <NavLink to="/feedback" className={link}>Beneficiary needs</NavLink>
        <NavLink to="/people" className={link}>People &amp; links</NavLink>
        <NavLink to="/settings" className={link}>Settings</NavLink>
        <div className="side-foot">
          <div className="small" style={{ fontWeight: 600 }}>{user?.name}</div>
          <div className="small muted" style={{ marginBottom: 8 }}>{user?.email}</div>
          <button className="btn-sm" style={{ width: '100%' }}
                  onClick={() => { logout(); nav('/login', { replace: true }) }}>
            Sign out
          </button>
        </div>
      </nav>
      <main className="main"><Outlet /></main>
    </div>
  )
}
