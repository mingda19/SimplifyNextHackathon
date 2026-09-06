import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Banner, Empty, Modal, Pill, ServiceDown, Stat } from '../components/ui'

const BLANK = { sku: '', name: '', category: '', unit: 'unit', on_hand: 0,
                reorder_point: 0, avg_daily_draw: 1, unit_cost_sgd: 0,
                preferred_vendor_id: '', dspi_series: '' }

const daysCover = it => (it.avg_daily_draw > 0 ? it.on_hand / it.avg_daily_draw : Infinity)

// One item's status tags. The category header collates the union of these, so a
// closed category still tells you whether anything inside needs attention.
function tagsFor(it, alerts, inbound) {
  const t = []
  if (it.on_hand <= 0) t.push({ k: 'danger', label: 'out of stock' })
  else if (it.on_hand < it.reorder_point) t.push({ k: 'danger', label: 'below reorder' })
  else if (daysCover(it) < 14) t.push({ k: 'warn', label: 'low cover' })
  if (alerts.some(a => a.sku === it.sku && a.type === 'EXPIRING_SOON'))
    t.push({ k: 'warn', label: 'expiring soon' })
  if (alerts.some(a => a.sku === it.sku && a.type === 'OVERSTOCKED'))
    t.push({ k: 'mute', label: 'overstocked' })
  if (inbound[it.sku]) t.push({ k: 'ok', label: 'on the way' })
  return t
}

export default function Stock() {
  const [items, setItems] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [inbound, setInbound] = useState({})
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')
  const [only, setOnly] = useState('all')
  const [openCats, setOpenCats] = useState({})
  const [editing, setEditing] = useState(null)
  const [moving, setMoving] = useState(null)

  const load = () => {
    setErr(null)
    api.stock().then(setItems).catch(setErr)
    api.alerts().then(a => setAlerts(Array.isArray(a) ? a : [])).catch(() => setAlerts([]))
    api.inbound().then(setInbound).catch(() => setInbound({}))
  }
  useEffect(load, [])

  const groups = useMemo(() => {
    if (!items) return []
    const term = q.trim().toLowerCase()
    const keep = items.filter(it => {
      if (term && !`${it.sku} ${it.name} ${it.category}`.toLowerCase().includes(term)) return false
      if (only === 'low') return it.on_hand < it.reorder_point
      if (only === 'expiring') return alerts.some(a => a.sku === it.sku && a.type === 'EXPIRING_SOON')
      if (only === 'inbound') return !!inbound[it.sku]
      return true
    })
    const by = {}
    for (const it of keep) (by[it.category || 'UNCATEGORISED'] ||= []).push(it)
    return Object.entries(by)
      .map(([cat, list]) => {
        // Collate every distinct tag inside the category, most severe first, so
        // the header carries the same information as opening it would.
        const seen = new Map()
        for (const it of list)
          for (const t of tagsFor(it, alerts, inbound))
            seen.set(t.label, { ...t, n: (seen.get(t.label)?.n || 0) + 1 })
        const rank = { danger: 0, warn: 1, ok: 2, mute: 3 }
        const tags = [...seen.values()].sort((a, b) => rank[a.k] - rank[b.k])
        return {
          cat,
          items: list.sort((a, b) => a.sku.localeCompare(b.sku)),
          tags,
          value: list.reduce((s, it) => s + it.on_hand * Number(it.unit_cost_sgd || 0), 0),
          needsAttention: tags.some(t => t.k === 'danger' || t.k === 'warn'),
        }
      })
      .sort((a, b) => Number(b.needsAttention) - Number(a.needsAttention) || a.cat.localeCompare(b.cat))
  }, [items, q, only, alerts, inbound])

  // Categories needing attention open by default; the rest stay collapsed.
  useEffect(() => {
    if (!items || Object.keys(openCats).length) return
    setOpenCats(Object.fromEntries(groups.map(g => [g.cat, g.needsAttention])))
  }, [items, groups])

  if (err) return <><h1>Stock</h1><ServiceDown name="Inventory service" error={err} /></>
  if (!items) return <><h1>Stock</h1><Empty>Loading</Empty></>

  const low = items.filter(it => it.on_hand < it.reorder_point).length
  const expiring = new Set(alerts.filter(a => a.type === 'EXPIRING_SOON').map(a => a.sku)).size
  const value = items.reduce((s, it) => s + it.on_hand * Number(it.unit_cost_sgd || 0), 0)
  const shown = groups.reduce((n, g) => n + g.items.length, 0)
  const allOpen = groups.length > 0 && groups.every(g => openCats[g.cat])

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Stock</h1>
          <p className="muted small" style={{ margin: 0 }}>
            Grouped by category. A category header carries the tags of everything inside it.
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

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="row">
          <input style={{ maxWidth: 260 }} placeholder="Search SKU, name or category"
                 value={q} onChange={e => setQ(e.target.value)} />
          <select style={{ maxWidth: 180 }} value={only} onChange={e => setOnly(e.target.value)}>
            <option value="all">All items</option>
            <option value="low">Below reorder point</option>
            <option value="expiring">Expiring soon</option>
            <option value="inbound">Has stock on the way</option>
          </select>
          <button className="btn-sm" onClick={() =>
            setOpenCats(Object.fromEntries(groups.map(g => [g.cat, !allOpen])))}>
            {allOpen ? 'Collapse all' : 'Expand all'}
          </button>
          <span className="muted small">{shown} item(s) in {groups.length} categories</span>
        </div>
      </div>

      {groups.length === 0 ? <Empty>Nothing matches that filter.</Empty> : groups.map(g => (
        <div className="card" key={g.cat} style={{ marginBottom: 10, padding: 0 }}>
          <button
            onClick={() => setOpenCats({ ...openCats, [g.cat]: !openCats[g.cat] })}
            style={{ width: '100%', border: 'none', background: 'none', padding: '13px 16px',
                     display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left',
                     borderRadius: 10, cursor: 'pointer' }}>
            <span className="muted" style={{ width: 12 }}>{openCats[g.cat] ? '▾' : '▸'}</span>
            <strong style={{ minWidth: 140 }}>{g.cat}</strong>
            <span className="muted small">{g.items.length} item{g.items.length === 1 ? '' : 's'}</span>
            <span className="row" style={{ gap: 5, flex: 1 }}>
              {g.tags.map(t => (
                <Pill key={t.label} kind={t.k}>{t.label}{t.n > 1 ? ` ${t.n}` : ''}</Pill>
              ))}
            </span>
            <span className="muted small">S${g.value.toFixed(0)}</span>
          </button>

          {openCats[g.cat] && (
            <div style={{ padding: '0 16px 12px', overflowX: 'auto' }}>
              <table>
                <thead><tr>
                  <th>SKU</th><th>Item</th><th className="num">On hand</th>
                  <th className="num">Reorder at</th><th className="num">Inbound</th>
                  <th>Tags</th><th></th>
                </tr></thead>
                <tbody>
                  {g.items.map(it => {
                    const inb = inbound[it.sku]
                    return (
                      <tr key={it.sku}>
                        <td className="mono small">{it.sku}</td>
                        <td>{it.name}</td>
                        <td className="num">{it.on_hand} <span className="muted small">{it.unit}</span></td>
                        <td className="num muted">{it.reorder_point}</td>
                        <td className="num">{inb
                          ? <span style={{ color: 'var(--ok)' }}>+{inb.qty_inbound}</span>
                          : <span className="muted">-</span>}</td>
                        <td><span className="row" style={{ gap: 4 }}>
                          {tagsFor(it, alerts, inbound).map(t =>
                            <Pill key={t.label} kind={t.k}>{t.label}</Pill>)}
                        </span></td>
                        <td style={{ textAlign: 'right' }}>
                          <div className="row" style={{ gap: 6, justifyContent: 'flex-end' }}>
                            <button className="btn-sm" onClick={() => setMoving(it)}>Move</button>
                            <button className="btn-sm" onClick={() => setEditing(it)}>Edit</button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      {editing && <ItemEditor item={editing === 'new' ? null : editing}
        prefill={typeof editing === 'object' && editing?.__prefill ? editing : null}
        onClose={() => setEditing(null)}
        onSaved={m => { setEditing(null); setNote(m); load(); setTimeout(() => setNote(''), 4000) }} />}
      {moving && <StockMovement item={moving} onClose={() => setMoving(null)}
        onSaved={m => { setMoving(null); setNote(m); load(); setTimeout(() => setNote(''), 4000) }} />}
    </>
  )
}

export function ItemEditor({ item, prefill, onClose, onSaved }) {
  const isNew = !item || item.__prefill
  const [form, setForm] = useState(
    item && !item.__prefill ? { ...BLANK, ...item }
      : { ...BLANK, ...(item?.__prefill || prefill || {}) })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = k => e => setForm({ ...form, [k]: e.target.value })

  const save = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    const num = v => (v === '' || v === null ? null : Number(v))
    const body = {
      name: form.name, category: (form.category || '').toUpperCase(), unit: form.unit,
      reorder_point: num(form.reorder_point), avg_daily_draw: num(form.avg_daily_draw),
      unit_cost_sgd: num(form.unit_cost_sgd),
      preferred_vendor_id: form.preferred_vendor_id || null,
      dspi_series: form.dspi_series || null,
    }
    try {
      if (isNew) {
        await api.createStock({ ...body, sku: form.sku.trim().toUpperCase(),
                                on_hand: num(form.on_hand) ?? 0 })
        onSaved(`Added ${form.sku.toUpperCase()}.`)
      } else {
        await api.updateStock(item.sku, body)
        onSaved(`Updated ${item.sku}.`)
      }
    } catch (ex) { setErr(ex.message); setBusy(false) }
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
                   placeholder="SOFT-FOOD-PACK" style={{ textTransform: 'uppercase' }} autoFocus />
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
          {isNew && (
            <div className="field"><label>Opening quantity</label>
              <input type="number" min="0" value={form.on_hand} onChange={set('on_hand')} /></div>
          )}
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
            <button className="btn-primary" disabled={busy}>{busy ? 'Saving' : 'Save'}</button>
          </div>
        </div>
      </form>
    </Modal>
  )
}

function StockMovement({ item, onClose, onSaved }) {
  const [detail, setDetail] = useState(null)
  const [dir, setDir] = useState('out')
  const [qty, setQty] = useState('')
  const [lotId, setLotId] = useState('')
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
      if (dir === 'out') {
        await api.allocate(item.sku, { lot_id: lotId, qty: n })
        onSaved(`Issued ${n} ${item.unit} of ${item.sku}.`)
      } else {
        await api.updateStock(item.sku, { on_hand: item.on_hand + n })
        onSaved(`Received ${n} ${item.unit} into ${item.sku}.`)
      }
    } catch (ex) { setErr(ex.message); setBusy(false) }
  }

  const lots = (detail?.lots || [])
  return (
    <Modal title={`Stock movement - ${item.sku}`} onClose={onClose}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {item.name} - {item.on_hand} {item.unit} on hand
      </p>
      <Banner>{err}</Banner>
      <div className="tabs">
        <button className={'tab' + (dir === 'out' ? ' active' : '')} onClick={() => setDir('out')}>Outgoing</button>
        <button className={'tab' + (dir === 'in' ? ' active' : '')} onClick={() => setDir('in')}>Incoming</button>
      </div>
      {dir === 'in' && (
        <div className="banner banner-warn small">
          For stock arriving against a purchase order, use <strong>Incoming orders</strong>
          {' '}instead. Receiving there books a lot with its own expiry and closes the order;
          this form only adjusts the running total.
        </div>
      )}
      <form onSubmit={submit}>
        {dir === 'out' && (
          <div className="field">
            <label>Draw from lot</label>
            <select value={lotId} onChange={e => setLotId(e.target.value)} required>
              {lots.length === 0 && <option value="">No lots recorded</option>}
              {lots.map(l => (
                <option key={l.lot_id} value={l.lot_id}>
                  {l.lot_id} - {l.qty} left, expires {l.expiry_date} ({l.source})
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label>{dir === 'out' ? 'Quantity to issue' : 'Quantity received'}</label>
          <input type="number" min="1" required value={qty} onChange={e => setQty(e.target.value)} autoFocus />
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy || (dir === 'out' && !lotId)}>
            {busy ? 'Recording' : dir === 'out' ? 'Issue stock' : 'Receive stock'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
