import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const t = getToken()
    if (!t) { setLoading(false); return }
    api.me()
      .then(r => setUser(r.user))
      .catch(() => setToken(null))     // expired or invalid — start clean
      .finally(() => setLoading(false))
  }, [])

  const login = async (email, password) => {
    const r = await api.login({ email, password })
    setToken(r.token); setUser(r.user); return r.user
  }
  const signup = async body => {
    const r = await api.signup(body)
    setToken(r.token); setUser(r.user); return r.user
  }
  const logout = () => { setToken(null); setUser(null) }

  return <AuthCtx.Provider value={{ user, loading, login, signup, logout }}>{children}</AuthCtx.Provider>
}
