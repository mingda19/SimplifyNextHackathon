import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Banner, Empty, Modal, Pill, ServiceDown, Stat } from '../components/ui'

// Receiving is a per-ORDER confirmation, not a per-item stock edit. The charity
// already told the agent what to buy; when the pallet turns up they tick it off
// rather than re-keying quantities one SKU at a time through Move.
export default function Orders() {
  const [orders, setOrders] = useState(null)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [tab, setTab] = useState('PLACED')
  const [receiving, setReceiving] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = () => api.orders().then(o => { setOrders(o); setErr(null) }).catch(setErr)
  useEffect(load, [])

  const shown = useMemo(
    () => (orders || []).filter(o => tab === 'ALL' || o.status === tab), [orders, tab])

  const receiveAll = async () => {
    const open = (orders || []).filter(o => o.status === 'PLACED')
    if (!open.length) return
    if (!confirm(`Mark all ${open.length} open orders as arrived? This books them into stock.`)) return
    setBusy(true)
    let ok = 0, failed = 0
    for (const o of open) {
      try { await api.receiveOrder(o.order_id); ok++ } catch { failed++ }
    }
    setNote(`Received ${ok} order${ok === 1 ? '' : 's'}${failed ? `, ${failed} failed` : ''}.`)
    setBusy(false); load()
  }

  if (err) return <><h1>Incoming orders</h1><ServiceDown name="Inventory service" error={err} /></>
  if (!orders) return <><h1>Incoming orders</h1><Empty>Loading</Empty></>

  const open = orders.filter(o => o.status === 'PLACED')
  const openValue = open.reduce((t, o) => t + (o.total_sgd || 0), 0)
  const overdue = open.filter(o => o.expected_at && new Date(o.expected_at) < new Date())

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Incoming orders</h1>
          <p className="muted small" style={{ margin: 0 }}>
            Stock that is paid for but not yet on the shelf. While an order is open its
            SKU is not re-flagged as low, so the agent will not re-order it.
          </p>
        </div>
        <div className="row">
          <button onClick={load}>Refresh</button>
          {open.length > 0 && (
            <button className="btn-primary" onClick={receiveAll} disabled={busy}>
              {busy ? 'Receiving' : `Receive all ${open.length}`}
            </button>
          )}
        </div>
      </div>

      <Banner kind="ok">{note}</Banner>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat n={open.length} l="open orders" />
        <Stat n={`S$${openValue.toFixed(0)}`} l="value in transit" />
        <Stat n={overdue.length} l="past expected date" kind={overdue.length ? 'warn' : undefined} />
        <Stat n={orders.filter(o => o.status === 'FULFILLED').length} l="received" />
      </div>

      <div className="tabs">
        {['PLACED', 'FULFILLED', 'CANCELLED', 'ALL'].map(t => (
          <button key={t} className={'tab' + (tab === t ? ' active' : '')} onClick={() => setTab(t)}>
            {t === 'PLACED' ? 'Open' : t === 'ALL' ? 'All' : t.toLowerCase()}
            {t === 'PLACED' && open.length > 0 ? ` (${open.length})` : ''}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <Empty>{tab === 'PLACED' ? 'Nothing on the way right now.' : 'Nothing here.'}</Empty>
      ) : (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr>
              <th>Item</th><th>Vendor</th><th className="num">Qty</th>
              <th className="num">Value</th><th>Expected</th><th>Status</th><th></th>
            </tr></thead>
            <tbody>
              {shown.map(o => {
                const late = o.expected_at && new Date(o.expected_at) < new Date()
                return (
                  <tr key={o.order_id}>
                    <td className="mono small">{o.sku}
                      <div className="muted" style={{ fontSize: '.75rem' }}>{o.order_id.slice(0, 18)}</div></td>
                    <td className="small">{o.vendor_id}</td>
                    <td className="num">{o.qty}</td>
                    <td className="num">S${(o.total_sgd || 0).toFixed(2)}</td>
                    <td className="small">
                      {o.expected_at ? new Date(o.expected_at).toLocaleDateString() : '-'}
                      {late && o.status === 'PLACED' ? <div><Pill kind="warn">overdue</Pill></div> : null}
                    </td>
                    <td>{o.status === 'PLACED' ? <Pill kind="warn">on the way</Pill>
                      : o.status === 'FULFILLED' ? <Pill kind="ok">received</Pill>
                      : <Pill>cancelled</Pill>}</td>
                    <td style={{ textAlign: 'right' }}>
                      {o.status === 'PLACED' && (
                        <button className="btn-sm btn-primary" onClick={() => setReceiving(o)}>
                          Mark arrived
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {receiving && <ReceiveModal order={receiving} onClose={() => setReceiving(null)}
        onDone={m => { setReceiving(null); setNote(m); load(); setTimeout(() => setNote(''), 5000) }} />}
    </>
  )
}

function ReceiveModal({ order, onClose, onDone }) {
  const [qty, setQty] = useState(order.qty)
  const [expiry, setExpiry] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async e => {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const r = await api.receiveOrder(order.order_id, {
        qty: Number(qty), ...(expiry ? { expiry_date: expiry } : {}),
      })
      onDone(`Received ${r.qty_received} x ${r.sku} into lot ${r.lot_id}. On hand: ${r.on_hand}.`)
    } catch (ex) { setErr(ex.message); setBusy(false) }
  }

  return (
    <Modal title={`Receive ${order.sku}`} onClose={onClose}>
      <p className="muted small" style={{ marginTop: 0 }}>
        {order.qty} ordered from {order.vendor_id} - S${(order.total_sgd || 0).toFixed(2)}
      </p>
      <form onSubmit={submit}>
        <Banner>{err}</Banner>
        <div className="field">
          <label>Quantity actually delivered</label>
          <input type="number" min="1" max={order.qty} required value={qty}
                 onChange={e => setQty(e.target.value)} autoFocus />
          <p className="muted small" style={{ marginTop: 6 }}>
            Short deliveries happen. Enter what physically arrived, not what was ordered.
          </p>
        </div>
        <div className="field">
          <label>Expiry date <span className="muted small">optional</span></label>
          <input type="date" value={expiry} onChange={e => setExpiry(e.target.value)} />
          <p className="muted small" style={{ marginTop: 6 }}>
            Received stock becomes a lot with its own expiry, which is what drives
            FEFO issuing and the expiring-soon alerts. Blank defaults to 180 days.
          </p>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>
            {busy ? 'Booking in' : 'Confirm arrival'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
