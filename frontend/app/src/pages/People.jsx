import { useEffect, useState } from 'react'
import { api } from '../api'
import { Banner, Empty, Modal, Pill, ServiceDown } from '../components/ui'

export default function People() {
  const [recipients, setRecipients] = useState([])
  const [links, setLinks] = useState([])
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)

  const load = () => {
    api.listRecipients().then(setRecipients).catch(setErr)
    api.listLinks().then(setLinks).catch(() => {})
  }
  useEffect(load, [])

  const newLink = async () => {
    const label = prompt('Label for this link (e.g. "Bedok branch")', 'Public request link')
    if (!label) return
    try { await api.createLink(label); setNote('Link created.'); load() }
    catch (ex) { setErr(ex) }
  }
  const revoke = async t => {
    if (!confirm('Revoke this link? Anyone holding it will no longer be able to send requests.')) return
    try { await api.revokeLink(t); setNote('Link revoked.'); load() } catch (ex) { setErr(ex) }
  }
  const copy = t => {
    const url = `${location.origin}/r/${t}`
    navigator.clipboard?.writeText(url)
    setNote(`Copied ${url}`)
    setTimeout(() => setNote(''), 4000)
  }

  if (err) return <><h1>People &amp; links</h1><ServiceDown name="Accounts service" error={err} /></>

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>People &amp; links</h1>
          <p className="muted small" style={{ margin: 0 }}>
            Two ways for a beneficiary to reach you. Neither gives any access beyond sending a request.
          </p>
        </div>
      </div>
      <Banner kind="ok">{note}</Banner>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="pagehead">
          <div>
            <h2>Public request links</h2>
            <p className="muted small" style={{ margin: 0 }}>
              No account needed. Best for elderly beneficiaries — print the link or send it over WhatsApp.
            </p>
          </div>
          <button className="btn-primary" onClick={newLink}>Create link</button>
        </div>
        {links.length === 0 ? <Empty>No links yet.</Empty> : (
          <table>
            <thead><tr><th>Label</th><th>Link</th><th className="num">Uses</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {links.map(l => (
                <tr key={l.token}>
                  <td>{l.label}</td>
                  <td className="mono small">/r/{l.token}</td>
                  <td className="num">{l.uses}</td>
                  <td>{l.is_active ? <Pill kind="ok">active</Pill> : <Pill>revoked</Pill>}</td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="row" style={{ gap: 6, justifyContent: 'flex-end' }}>
                      <button className="btn-sm" onClick={() => copy(l.token)}>Copy</button>
                      {l.is_active && <button className="btn-sm btn-danger" onClick={() => revoke(l.token)}>Revoke</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="pagehead">
          <div>
            <h2>Recipient accounts</h2>
            <p className="muted small" style={{ margin: 0 }}>
              A named login that only ever sees the request screen. Recipients cannot self-register.
            </p>
          </div>
          <button onClick={() => setAdding(true)}>Add recipient</button>
        </div>
        {recipients.length === 0 ? <Empty>No recipient accounts yet.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Beneficiary ID</th><th>Last sign-in</th></tr></thead>
            <tbody>
              {recipients.map(r => (
                <tr key={r.id}>
                  <td>{r.display_name}</td>
                  <td className="small">{r.email}</td>
                  <td className="mono small">{r.beneficiary_id}</td>
                  <td className="muted small">
                    {r.last_login_at ? new Date(r.last_login_at).toLocaleString() : 'never'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {adding && <AddRecipient onClose={() => setAdding(false)}
        onSaved={m => { setAdding(false); setNote(m); load() }} />}
    </>
  )
}

function AddRecipient({ onClose, onSaved }) {
  const [form, setForm] = useState({ display_name: '', email: '', password: '', beneficiary_id: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setForm({ ...form, [k]: e.target.value })

  const save = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const r = await api.createRecipient({ ...form, beneficiary_id: form.beneficiary_id || undefined })
      onSaved(`Created ${r.display_name} (${r.beneficiary_id}). Give them the password you just set.`)
    } catch (ex) { setErr(ex.message); setBusy(false) }
  }

  return (
    <Modal title="Add a recipient account" onClose={onClose}>
      <form onSubmit={save}>
        <Banner>{err}</Banner>
        <div className="field"><label>Name</label>
          <input required value={form.display_name} onChange={set('display_name')} /></div>
        <div className="field"><label>Email</label>
          <input type="email" required value={form.email} onChange={set('email')} /></div>
        <div className="field"><label>Temporary password</label>
          <input type="text" required value={form.password} onChange={set('password')}
                 placeholder="min 10 chars, upper, lower, number" />
          <p className="muted small" style={{ marginTop: 6 }}>
            Shown as plain text so you can read it out to them.
          </p></div>
        <div className="field"><label>Beneficiary ID <span className="muted small">optional</span></label>
          <input value={form.beneficiary_id} onChange={set('beneficiary_id')} placeholder="generated if blank" /></div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
        </div>
      </form>
    </Modal>
  )
}
