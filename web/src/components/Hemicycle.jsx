import { useMemo, useState } from 'react'
import { CAUCUS, initials, lastName } from '../util.js'

const W = 900
const H = 470
const CX = W / 2
const CY = H - 30
const ROWS = 6
const R0 = 175
const R1 = 410

// Classic parliament layout: seats spread over concentric arcs, rows sized to their radius.
function layout(n) {
  const radii = Array.from({ length: ROWS }, (_, i) => R0 + (i * (R1 - R0)) / (ROWS - 1))
  const total = radii.reduce((a, b) => a + b, 0)
  let counts = radii.map((r) => Math.floor((n * r) / total))
  let left = n - counts.reduce((a, b) => a + b, 0)
  for (let i = ROWS - 1; left > 0; i = (i - 1 + ROWS) % ROWS, left--) counts[i]++
  const seats = []
  radii.forEach((r, i) => {
    const k = counts[i]
    for (let j = 0; j < k; j++) {
      const a = Math.PI - (Math.PI * (j + 0.5)) / k
      seats.push({ x: CX + r * Math.cos(a), y: CY - r * Math.sin(a), angle: a, row: i })
    }
  })
  // Left to right across the chamber, then inner to outer.
  return seats.sort((s, t) => t.angle - s.angle || s.row - t.row)
}

const SEATS = layout(100)
const SEAT_R = 16

export default function Hemicycle({ senators, order, colorOf, ringOf, selected, onSelect, highlight, center, labelOf }) {
  const [hover, setHover] = useState(null)
  const position = useMemo(() => {
    const m = new Map()
    order.forEach((id, i) => m.set(id, SEATS[i]))
    return m
  }, [order])
  const byId = useMemo(() => new Map(senators.map((s) => [s.id, s])), [senators])
  const hovered = hover ? byId.get(hover) : null
  const hp = hover ? position.get(hover) : null

  return (
    <div className="hemicycle">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Senate chamber, one circle per senator">
        <defs>
          <radialGradient id="floor" cx="50%" cy="100%" r="80%">
            <stop offset="0%" stopColor="#0f2233" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#05080d" stopOpacity="0" />
          </radialGradient>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <path d={`M ${CX - R1 - 40} ${CY} A ${R1 + 40} ${R1 + 40} 0 0 1 ${CX + R1 + 40} ${CY} Z`} fill="url(#floor)" />
        {[R0 - 30, R1 + 28].map((r) => (
          <path key={r} d={`M ${CX - r} ${CY} A ${r} ${r} 0 0 1 ${CX + r} ${CY}`} fill="none" stroke="#1d3446" strokeDasharray="2 6" />
        ))}
        <line x1={CX} y1={CY - R1 - 34} x2={CX} y2={CY - R0 + 40} stroke="#1d3446" strokeDasharray="3 5" />
        {senators.map((s, idx) => {
          const p = position.get(s.id)
          if (!p) return null
          const isSel = selected === s.id
          const dim = highlight && !highlight.has(s.id)
          return (
            <g
              key={s.id}
              className={`seat ${isSel ? 'sel' : ''} ${dim ? 'dim' : ''}`}
              style={{ transform: `translate(${p.x}px, ${p.y}px)` }}
              onMouseEnter={() => setHover(s.id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect(isSel ? null : s.id)}
              onKeyDown={(e) => e.key === 'Enter' && onSelect(isSel ? null : s.id)}
              tabIndex={0}
              role="button"
              aria-label={`${s.name}, ${s.state}`}
            >
              <g className="seat-in" style={{ animationDelay: `${Math.round((Math.PI - p.angle) * 260 + p.row * 40)}ms` }}>
                <circle r={SEAT_R + 3} fill="none" stroke={ringOf ? ringOf(s) : CAUCUS[s.caucus]?.color} strokeWidth="2.2" opacity="0.9" className="seat-ring" />
                <circle r={SEAT_R} fill={colorOf(s)} className="seat-core" />
                {s.incoming && <circle r={3} cx={SEAT_R - 2} cy={-SEAT_R + 2} fill="#e8f6ff" />}
                <text className="seat-label" y="4">{labelOf ? labelOf(s) : initials(s.name)}</text>
              </g>
            </g>
          )
        })}
        <g className="chamber-center">{center}</g>
      </svg>
      {hovered && hp && (
        <div className="seat-tip" style={{ left: `${(hp.x / W) * 100}%`, top: `${(hp.y / H) * 100}%` }}>
          <b>{lastName(hovered.name)}</b> <span>{hovered.state} · {hovered.caucus}</span>
        </div>
      )}
    </div>
  )
}
