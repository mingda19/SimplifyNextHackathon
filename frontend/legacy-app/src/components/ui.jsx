export const Pill = ({ kind = 'mute', children }) =>
  <span className={`pill pill-${kind}`}>{children}</span>

export const Banner = ({ kind = 'err', children }) =>
  children ? <div className={`banner banner-${kind}`}>{children}</div> : null

export const Stat = ({ n, l, kind }) => (
  <div className="stat">
    <div className="n" style={kind === 'danger' ? { color: 'var(--danger)' }
      : kind === 'warn' ? { color: 'var(--warn)' } : undefined}>{n}</div>
    <div className="l">{l}</div>
  </div>
)

export const Empty = ({ children }) => <div className="card empty">{children}</div>

export function Modal({ title, onClose, children }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="pagehead"><h2>{title}</h2>
          <button className="btn-sm" onClick={onClose}>Close</button></div>
        {children}
      </div>
    </div>
  )
}

// A service being down is an expected state in a multi-service demo. Say which
// one and how to start it, rather than showing an empty table that looks like
// "you have no stock".
export function ServiceDown({ name, error }) {
  return (
    <div className="banner banner-warn">
      <strong>{name} is unreachable.</strong>{' '}
      {error?.offline ? 'Start it with ./scripts/run_stack.sh' : error?.message}
    </div>
  )
}
