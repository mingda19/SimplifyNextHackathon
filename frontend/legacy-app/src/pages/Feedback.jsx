import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, Pill, ServiceDown, Stat } from '../components/ui'

export default function Feedback() {
  const [needs, setNeeds] = useState(null)
  const [entries, setEntries] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [err, setErr] = useState(null)
  const [tab, setTab] = useState('needs')

  useEffect(() => {
    api.unmetNeeds().then(setNeeds).catch(setErr)
    api.feedback().then(r => setEntries(Array.isArray(r) ? r : [])).catch(() => {})
    api.feedbackMetrics().then(setMetrics).catch(() => {})
  }, [])

  if (err) return <><h1>Beneficiary needs</h1><ServiceDown name="Feedback service" error={err} /></>
  if (!needs) return <><h1>Beneficiary needs</h1><Empty>Loading…</Empty></>

  const ranked = needs.ranked || []
  const gaps = ranked.filter(r => r.gap)

  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Beneficiary needs</h1>
          <p className="muted small" style={{ margin: 0 }}>
            What people actually asked for, ranked by how many raised it × how urgent it is.
          </p>
        </div>
      </div>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat n={needs.totals?.entries_considered ?? 0} l="messages analysed" />
        <Stat n={ranked.length} l="distinct needs" />
        <Stat n={gaps.length} l="needs nothing stocks" kind={gaps.length ? 'danger' : undefined} />
        <Stat n={metrics ? `${Math.round((metrics.sku_resolution_rate || 0) * 100)}%` : '—'}
              l="terms matched to stock" />
      </div>

      <div className="tabs">
        <button className={'tab' + (tab === 'needs' ? ' active' : '')} onClick={() => setTab('needs')}>
          Ranked needs
        </button>
        <button className={'tab' + (tab === 'messages' ? ' active' : '')} onClick={() => setTab('messages')}>
          Messages ({entries.length})
        </button>
      </div>

      {tab === 'needs' ? (
        ranked.length === 0 ? <Empty>No needs extracted yet.</Empty> : (
          <div className="grid" style={{ gap: 10 }}>
            {ranked.slice(0, 40).map((r, i) => (
              <div key={i} className="card">
                <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 240 }}>
                    <div style={{ fontWeight: 600 }}>{r.need}</div>
                    <div className="muted small">
                      {r.frequency} {r.frequency === 1 ? 'person' : 'people'} · urgency {r.urgency}
                      {r.suggested_category && ` · ${r.suggested_category.replace(/_/g, ' ')}`}
                    </div>
                    {r.mentioned_skus?.length > 0 && (
                      <div className="small" style={{ marginTop: 6 }}>
                        Stocked as: {r.mentioned_skus.map(s => <span key={s} className="mono">{s} </span>)}
                      </div>
                    )}
                    {r.near_misses?.map((nm, j) => (
                      <div key={j} className="small" style={{ marginTop: 6, color: 'var(--warn)' }}>
                        Closest stocked item is <span className="mono">{nm.near_sku}</span>, but it
                        does not meet <strong>{nm.unmet_qualifier}</strong> — refused rather than
                        substituted.
                      </div>
                    ))}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{r.score}</div>
                    <div className="muted small">score</div>
                    {r.gap && <div style={{ marginTop: 6 }}><Pill kind="danger">nothing stocked</Pill></div>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        entries.length === 0 ? <Empty>No messages yet.</Empty> : (
          <div className="card" style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>From</th><th>Message</th><th>Urgency</th><th>Matched</th><th>Received</th></tr></thead>
              <tbody>
                {entries.slice(0, 100).map(e => (
                  <tr key={e.id}>
                    <td className="small mono">{e.beneficiary_id}<div className="muted">{e.lang} · {e.channel}</div></td>
                    <td style={{ maxWidth: 380 }}>
                      <div>{e.text}</div>
                      {e.summary_en && e.detected_lang !== 'en' &&
                        <div className="muted small" style={{ marginTop: 4 }}>{e.summary_en}</div>}
                    </td>
                    <td>{e.urgency ? <Pill kind={e.urgency >= 4 ? 'danger' : e.urgency === 3 ? 'warn' : 'mute'}>
                      {e.urgency}</Pill> : <span className="muted">—</span>}</td>
                    <td className="small mono">{(e.mentioned_skus || []).join(', ') || <span className="muted">—</span>}</td>
                    <td className="muted small">{new Date(e.received_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </>
  )
}
