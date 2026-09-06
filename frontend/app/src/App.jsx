import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Shell from './pages/Shell'
import Stock from './pages/Stock'
import Orders from './pages/Orders'
import AgentActions from './pages/AgentActions'
import Feedback from './pages/Feedback'
import People from './pages/People'
import RequestPage from './pages/RequestPage'

// Recipients get exactly one screen. The server enforces this too
// (require_charity); the routing here is convenience, not the security boundary.
function Protected({ children, charityOnly = true }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-wrap"><span className="muted">Loading…</span></div>
  if (!user) return <Navigate to="/login" replace />
  if (charityOnly && user.role !== 'charity') return <Navigate to="/request" replace />
  return children
}

export default function App() {
  const { user } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/signup" element={user ? <Navigate to="/" replace /> : <Signup />} />

      {/* Public: handed out by a charity. No account, no admin access. */}
      <Route path="/r/:token" element={<RequestPage />} />
      {/* Signed-in recipient — same screen, prefilled identity. */}
      <Route path="/request" element={<RequestPage />} />

      <Route element={<Protected><Shell /></Protected>}>
        <Route path="/" element={<Navigate to="/stock" replace />} />
        <Route path="/stock" element={<Stock />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/agent" element={<AgentActions />} />
        <Route path="/feedback" element={<Feedback />} />
        <Route path="/people" element={<People />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
