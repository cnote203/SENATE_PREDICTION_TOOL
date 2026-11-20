// Dimension metadata comes from meta.json (one entry per sector), keyed by dimension id.
export function dimensionIndex(meta) {
  const out = {}
  for (const m of meta.modules) for (const d of m.dimensions) out[d.id] = { ...d, module: m.id }
  return out
}

export const SECTOR_SHORT = {
  foreign_policy: 'Foreign policy', healthcare: 'Health', energy: 'Energy', banking: 'Banking', tech: 'AI & tech',
}

export const CAUCUS = {
  D: { label: 'Democratic caucus', color: '#5b8bd9' },
  R: { label: 'Republican conference', color: '#c2414f' },
  I: { label: 'Independent', color: '#9a86c9' },
}

export const SOURCE = {
  votes: { label: 'Votes', note: 'Estimated from this senator’s own roll-call votes' },
  fitted: { label: 'Mapped', note: 'Ideology mapping from a House record' },
  'fitted+donors': { label: 'Mapped + PACs', note: 'House-record mapping adjusted by PAC donor history' },
  formula: { label: 'Prior', note: 'Starting formula: no usable roll calls on this dimension' },
  imputed: { label: 'Imputed', note: 'No voting record: caucus estimate, adjusted for state' },
  override: { label: 'Override', note: 'Hand-set from cited roll calls' },
}

const STOPS = [
  [-2, [126, 167, 214]],
  [-0.7, [72, 103, 140]],
  [0, [58, 68, 84]],
  [0.7, [160, 125, 62]],
  [2, [222, 186, 110]],
]

export function scoreColor(v) {
  if (v == null || Number.isNaN(v)) return '#3a4454'
  const x = Math.max(-2, Math.min(2, v))
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [a, ca] = STOPS[i]
    const [b, cb] = STOPS[i + 1]
    if (x <= b) {
      const t = (x - a) / (b - a)
      const c = ca.map((c0, k) => Math.round(c0 + (cb[k] - c0) * t))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return 'rgb(222,186,110)'
}

export function probColor(p) {
  // 0 = Nay (red-violet), 0.5 = undecided (slate), 1 = Yea (green)
  if (p == null) return '#3a4454'
  const lerp = (a, b, t) => Math.round(a + (b - a) * t)
  const nay = [194, 65, 79]
  const mid = [58, 68, 84]
  const yea = [110, 176, 132]
  const [a, b, t] = p < 0.5 ? [nay, mid, p / 0.5] : [mid, yea, (p - 0.5) / 0.5]
  return `rgb(${lerp(a[0], b[0], t)},${lerp(a[1], b[1], t)},${lerp(a[2], b[2], t)})`
}

export const pct = (p, digits = 0) => (p == null ? '—' : `${(p * 100).toFixed(digits)}%`)
export const fmtScore = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}`)
export const money = (v) =>
  v == null ? '—' : v >= 1000 ? `$${(v / 1000).toFixed(v >= 100000 ? 0 : 1)}k` : `$${Math.round(v)}`

export function lastName(name) {
  const parts = name.replace(/,? (Jr\.|Sr\.|III|II)$/, '').split(' ')
  return parts[parts.length - 1]
}

export function initials(name) {
  const p = name.replace(/,? (Jr\.|Sr\.|III|II)$/, '').split(' ').filter(Boolean)
  return (p[0][0] + p[p.length - 1][0]).toUpperCase()
}

export const THRESHOLD_LABEL = {
  majority: 'simple majority',
  cloture: '60 votes for cloture',
  two_thirds: 'two-thirds',
}

// Dimension end labels are stored in capitals; show them in sentence case.
export const tag = (t = '') => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase()

export function thresholdNeed(threshold, voting) {
  if (threshold === 'cloture') return 60
  if (threshold === 'two_thirds') return Math.ceil((2 * voting) / 3)
  return Math.floor(voting / 2) + 1
}
