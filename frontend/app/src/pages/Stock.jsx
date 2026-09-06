import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { Banner, Empty, Modal, Pill, ServiceDown, Stat } from '../components/ui'

const BLANK = { sku: '', name: '', category: '', unit: 'unit', on_hand: 0,
                reorder_point: 0, avg_daily_draw: 1, unit_cost_sgd: 0,
                preferred_vendor_id: '', dspi_series: '' }

const daysCover = it => (it.avg_daily_draw > 0 ? it.on_hand / it.avg_daily_draw : Infinity)

function coverPill(it) {
  const d = daysCover(it)
  if (it.on_hand <= 0) return <Pill kind="danger">out of stock</Pill>
  if (it.on_hand < it.reorder_point) return <Pill kind="danger">below reorder</Pill>
  if (d < 14) return <Pill kind="warn">{d.toFixed(0)}d cover</Pill>
  return <Pill kind="ok">{Number.isFinite(d) ? `${d.toFixed(0)}d cover` : 'stocked'}</Pill>
}

export default function Stock() {
  const [items, setItems] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')
  const [only, setOnly] = useState('all')
  const [editing, setEditing] = useState(null)   // item | 'new'
  const [moving, setMoving] = useState(null)     // item for stock movement

  const load = () => {
    setErr(null)
    api.stock().then(setItems).catch(setErr)
    api.alerts().then(a => setAlerts(Array.isArray(a) ? a : [])).catch(() => setAlerts([]))
  }
  useEffect(load, [])

  const shown = useMemo(() => {
    if (!items) return []
    const term = q.trim().toLowerCase()
    return items.filter(it => {
      if (term && !(`${it.sku} ${it.name} ${it.category}`.toLowerCase().includes(term))) return false
      if (only === 'low') return it.on_hand < it.reorder_point
      if (only === 'expiring') return alerts.some(a => a.sku === it.sku && a.type === 'EXPIRING_SOON')
      return true
    })
  }, [items, q, only, alerts])

  if (err) return <><h1>Stock</h1><ServiceDown name="Inventory service" error={err} /></>
  if (!items) return <><h1>Stock</h1><Empty>Loading…</Empty></>

  const low = items.filter(it => it.on_hand < it.reorder_point).length
  const expiring = new Set(alerts.filter(a => a.type === 'EXPIRING_SOON').map(a => a.sku)).size
  const value = items.reduce((s, it) => s + it.on_hand * Number(it.unit_cost_sgd || 0), 0)

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Stock</h1>
          <p className="muted small" style={{ margin: 0 }}>
            Live from the inventory service. Movements are recorded against lots.
          </p>
        </div>
        <div className="row">
          <button onClick={load}>Refresh</button>
          <button className="btn-primary" onClick={() => setEditing('new')}>Add item</button>
        </div>
      </div>

      <Banner kind="ok">{note}</Banner>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat n={items.length} l="items tracked" />
        <Stat n={low} l="below reorder point" kind={low ? 'danger' : undefined} />
        <Stat n={expiring} l="expiring soon" kind={expiring ? 'warn' : undefined} />
        <Stat n={`S$${value.toFixed(0)}`} l="stock at cost" />
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <input style={{ maxWidth: 280 }} placeholder="Search SKU, name or category"
                 value={q} onChange={e => setQ(e.target.value)} />
          <select style={{ maxWidth: 190 }} value={only} onChange={e => setOnly(e.target.value)}>
            <option value="all">All items</option>
            <option value="low">Below reorder point</option>
            <option value="expiring">Expiring soon</option>
          </select>
          <span className="muted small">{shown.length} shown</span>
        </div>

        {shown.length === 0 ? <Empty>Nothing matches that filter.</Empty> : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr>
                <th>SKU</th><th>Item</th><th>Category</th>
                <th className="num">On hand</th><th className="num">Reorder at</th>
                <th className="num">Daily draw</th><th>Status</th><th></th>
              </tr></thead>
              <tbody>
                {shown.map(it => (
                  <tr key={it.sku}>
                    <td className="mono">{it.sku}</td>
                    <td>{it.name}</td>
                    <td className="muted small">{it.category}</td>
                    <td className="num">{it.on_hand} <span className="muted small">{it.unit}</span></td>
                    <td className="num muted">{it.reorder_point}</td>
                    <td className="num muted">{it.avg_daily_draw}</td>
                    <td>{coverPill(it)}</td>
                    <td>
                      <div className="row" style={{ gap: 6, justifyContent: 'flex-end' }}>
                        <button className="btn-sm" onClick={() => setMoving(it)}>Move</button>
                        <button className="btn-sm" onClick={() => setEditing(it)}>Edit</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && <ItemEditor item={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)}
        onSaved={m => { setEditing(null); setNote(m); load(); setTimeout(() => setNote(''), 4000) }} />}
      {moving && <StockMovement item={moving} onClose={() => setMoving(null)}
        onSaved={m => { setMoving(null); setNote(m); load(); setTimeout(() => setNote(''), 4000) }} />}
    </>
  )
}

function ItemEditor({ item, onClose, onSaved }) {
  const isNew = !item
  const [form, setForm] = useState(item ? { ...BLANK, ...item } : BLANK)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setForm({ ...form, [k]: e.target.value })

  const save = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    const num = v => (v === '' || v === null ? null : Number(v))
    const body = {
      name: form.name, category: form.category, unit: form.unit,
      reorder_point: num(form.reorder_point), avg_daily_draw: num(form.avg_daily_draw),
      unit_cost_sgd: num(form.unit_cost_sgd),
      preferred_vendor_id: form.preferred_vendor_id || null,
      dspi_series: form.dspi_series || null,
    }
    try {
      if (isNew) {
        await api.createStock({ ...body, sku: form.sku.trim().toUpperCase(),
                                on_hand: 0 })
        onSaved(`Added ${form.sku.toUpperCase()}.`)
      } else {
        await api.updateStock(item.sku, body)
        onSaved(`Updated ${item.sku}.`)
      }
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirm(`Delete ${item.sku}? This cannot be undone.`)) return
    setBusy(true)
    try { await api.deleteStock(item.sku); onSaved(`Deleted ${item.sku}.`) }
    catch (ex) { setErr(ex.message); setBusy(false) }
  }

  return (
    <Modal title={isNew ? 'Add stock item' : `Edit ${item.sku}`} onClose={onClose}>
      <form onSubmit={save}>
        <Banner>{err}</Banner>
        {isNew && (
          <div className="field">
            <label>SKU code</label>
            <input required value={form.sku} onChange={set('sku')}
                   placeholder="RICE-10KG" style={{ textTransform: 'uppercase' }} />
          </div>
        )}
        <div className="field"><label>Name</label>
          <input required value={form.name} onChange={set('name')} /></div>
        <div className="grid g2">
          <div className="field"><label>Category</label>
            <input required value={form.category} onChange={set('category')} placeholder="STAPLES" /></div>
          <div className="field"><label>Unit</label>
            <input required value={form.unit} onChange={set('unit')} placeholder="bag" /></div>
        </div>
        <div className="grid g2">
          {isNew && <p className="muted small">After adding the item, use Move → Incoming to record its opening lots.</p>}
          <div className="field"><label>Reorder point</label>
            <input type="number" min="0" required value={form.reorder_point} onChange={set('reorder_point')} /></div>
          <div className="field"><label>Average daily draw</label>
            <input type="number" min="0" required value={form.avg_daily_draw} onChange={set('avg_daily_draw')} /></div>
          <div className="field"><label>Unit cost (S$)</label>
            <input type="number" step="0.01" min="0" required value={form.unit_cost_sgd} onChange={set('unit_cost_sgd')} /></div>
        </div>
        <div className="field"><label>Preferred vendor <span className="muted small">optional</span></label>
          <input value={form.preferred_vendor_id || ''} onChange={set('preferred_vendor_id')} placeholder="VENDOR-HARVEST" /></div>
        <div className="row" style={{ justifyContent: 'space-between', marginTop: 6 }}>
          {!isNew ? <button type="button" className="btn-danger" onClick={remove} disabled={busy}>Delete</button> : <span />}
          <div className="row">
            <button type="button" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

// Incoming and outgoing are handled differently on purpose. Incoming stock is a
// new lot (it has its own expiry). Outgoing is an allocation against an
// existing lot, which is what lets the service enforce FEFO and refuse to draw
// from an expired lot — the LOT_EXPIRED error the agent adapts to.
function StockMovement({ item, onClose, onSaved }) {
  const [detail, setDetail] = useState(null)
  const [dir, setDir] = useState('out')
  const [qty, setQty] = useState('')
  const [lotId, setLotId] = useState('')
  const [expiry, setExpiry] = useState('')
  const [source, setSource] = useState('DONATED')
  const operation = useRef(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.stockItem(item.sku).then(d => {
      setDetail(d)
      const live = (d.lots || []).filter(l => l.qty > 0)
      if (live.length) setLotId(live[0].lot_id)
    }).catch(e => setErr(e.message))
  }, [item.sku])

  const submit = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    const n = Number(qty)
    try {
      const fingerprint = JSON.stringify([dir, n, lotId, expiry, source])
      if (operation.current?.fingerprint !== fingerprint)
        operation.current = { fingerprint, key: crypto.randomUUID() }
      if (dir === 'out') {
        await api.allocate(item.sku, { lot_id: lotId, qty: n }, operation.current.key)
        onSaved(`Issued ${n} ${item.unit} of ${item.sku}.`)
      } else {
        await api.receive(item.sku, { qty: n, expiry_date: expiry, source }, operation.current.key)
        onSaved(`Received ${n} ${item.unit} into ${item.sku}.`)
      }
    } catch (ex) { setErr(ex.message); setBusy(false) }
  }

  const lots = (detail?.lots || [])
  return (
    <Modal title={`Stock movement — ${item.sku}`} onClose={onClose}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {item.name} · {item.on_hand} {item.unit} on hand
      </p>
      <Banner>{err}</Banner>
      <div className="tabs">
        <button className={'tab' + (dir === 'out' ? ' active' : '')} onClick={() => setDir('out')}>Outgoing</button>
        <button className={'tab' + (dir === 'in' ? ' active' : '')} onClick={() => setDir('in')}>Incoming</button>
      </div>
      <form onSubmit={submit}>
        {dir === 'in' && <div className="grid g2">
          <div className="field"><label>Expiry date</label>
            <input type="date" required value={expiry} onChange={e => setExpiry(e.target.value)} /></div>
          <div className="field"><label>Source</label>
            <select value={source} onChange={e => setSource(e.target.value)}>
              <option value="DONATED">Donated</option><option value="PURCHASED">Purchased</option>
            </select></div>
        </div>}
        {dir === 'out' && (
          <div className="field">
            <label>Draw from lot</label>
            <select value={lotId} onChange={e => setLotId(e.target.value)} required>
              {lots.length === 0 && <option value="">No lots recorded</option>}
              {lots.map(l => (
                <option key={l.lot_id} value={l.lot_id}>
                  {l.lot_id} — {l.qty} left, expires {l.expiry_date} ({l.source})
                </option>
              ))}
            </select>
            <p className="muted small" style={{ marginTop: 6 }}>
              Choose a lot with stock available and a valid expiry date.
            </p>
          </div>
        )}
        <div className="field">
          <label>{dir === 'out' ? 'Quantity to issue' : 'Quantity received'}</label>
          <input type="number" min="1" max="2147483647" step="1" required value={qty} onChange={e => setQty(e.target.value)} autoFocus />
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy || (dir === 'out' && !lotId)}>
            {busy ? 'Recording…' : dir === 'out' ? 'Issue stock' : 'Receive stock'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
