// One place that knows how to reach every backend service.
// Paths go through the Vite proxy (see vite.config.js) so the browser stays on
// a single origin and CORS never becomes a demo-day problem.

const TOKEN_KEY = 'pantry.token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = t => t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {}
  if (body !== undefined) headers['content-type'] = 'application/json'
  const token = getToken()
  if (auth && token) headers['Authorization'] = `Bearer ${token}`

  let res
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    // A service being down is a normal state here, not a crash — the charity
    // should see which part is unavailable, not a blank screen.
    throw Object.assign(new Error('Service unreachable'), { offline: true, path })
  }

  if (res.status === 204) return null
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }

  if (!res.ok) {
    const detail = data?.detail ?? data
    const message = typeof detail === 'string' ? detail
      : detail?.message || `Request failed (${res.status})`
    throw Object.assign(new Error(message), { status: res.status, detail })
  }
  return data
}

export const api = {
  // --- auth ---------------------------------------------------------------
  passwordPolicy: () => request('/api/auth/auth/password-policy', { auth: false }),
  signup: b => request('/api/auth/auth/signup', { method: 'POST', body: b, auth: false }),
  login:  b => request('/api/auth/auth/login',  { method: 'POST', body: b, auth: false }),
  me:     () => request('/api/auth/auth/me'),
  listRecipients: () => request('/api/auth/auth/recipients'),
  createRecipient: b => request('/api/auth/auth/recipients', { method: 'POST', body: b }),
  listLinks: () => request('/api/auth/auth/request-links'),
  createLink: label => request(`/api/auth/auth/request-links?label=${encodeURIComponent(label)}`, { method: 'POST' }),
  revokeLink: t => request(`/api/auth/auth/request-links/${t}`, { method: 'DELETE' }),
  resolveLink: t => request(`/api/auth/auth/request-links/${t}`, { auth: false }),
  markLinkUsed: t => request(`/api/auth/auth/request-links/${t}/used`, { method: 'POST', auth: false }),

  // --- inventory ----------------------------------------------------------
  stock: () => request('/api/inventory/inventory'),
  stockItem: sku => request(`/api/inventory/inventory/${encodeURIComponent(sku)}`),
  createStock: b => request('/api/inventory/inventory', { method: 'POST', body: b }),
  updateStock: (sku, b) => request(`/api/inventory/inventory/${encodeURIComponent(sku)}`, { method: 'PATCH', body: b }),
  deleteStock: sku => request(`/api/inventory/inventory/${encodeURIComponent(sku)}`, { method: 'DELETE' }),
  allocate: (sku, b) => request(`/api/inventory/inventory/${encodeURIComponent(sku)}/allocate`, { method: 'POST', body: b }),
  alerts: () => request('/api/inventory/inventory/alerts'),

  // --- feedback -----------------------------------------------------------
  submitFeedback: b => request('/api/feedback/feedback', { method: 'POST', body: b, auth: false }),
  feedback: q => request(`/api/feedback/feedback${q ? '?' + q : ''}`),
  unmetNeeds: () => request('/api/feedback/feedback/unmet-needs'),
  feedbackMetrics: () => request('/api/feedback/metrics'),

  // --- pricing ------------------------------------------------------------
  forecast: series => request(`/api/pricing/price/forecast?series=${encodeURIComponent(series)}`, { auth: false }),
  forecastAll: () => request('/api/pricing/price/forecast/all', { auth: false }),

  // --- agent --------------------------------------------------------------
  decide: (id, decision, by, approved_steps) => request(`/api/agent/agent/runs/${id}/decision`, {
    method: 'POST',
    body: approved_steps === undefined
      ? { decision, decided_by: by }
      : { decision, decided_by: by, approved_steps },
  }),
  runs: status => request(`/api/agent/agent/runs${status ? '?status=' + status : ''}`),
  run: id => request(`/api/agent/agent/runs/${id}`),
  startRun: charity_type => request('/api/agent/agent/runs', { method: 'POST', body: { charity_type } }),
  decide: (id, decision, by) => request(`/api/agent/agent/runs/${id}/decision`, { method: 'POST', body: { decision, decided_by: by } }),
}
