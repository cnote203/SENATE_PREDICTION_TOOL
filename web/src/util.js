export const DIMENSIONS = {
  nato_interventionism: { label: 'Interventionism', short: 'INTV', lowTag: 'RESTRAINT', highTag: 'HAWKISH' },
  defense_budget: { label: 'Defense budget', short: 'DEF$', lowTag: 'CUT', highTag: 'INCREASE' },
  arms_sales_oversight: { label: 'Arms-sale oversight', short: 'ARMS', lowTag: 'DEFER', highTag: 'BLOCK' },
  china_decoupling: { label: 'China decoupling', short: 'PRC', lowTag: 'ENGAGE', highTag: 'DECOUPLE' },
}

export const CAUCUS = {
  D: { label: 'Democratic caucus', color: '#3d8bff' },
  R: { label: 'Republican conference', color: '#ff4d5e' },
  I: { label: 'Independent', color: '#b07cff' },
}

export const SOURCE = {
  votes: { label: 'VOTES', note: 'Estimated from this senator’s own roll-call votes' },
  fitted: { label: 'MAPPED', note: 'Ideology mapping from a House record' },
  'fitted+donors': { label: 'MAPPED+$', note: 'House-record mapping adjusted by PAC donor history' },
  formula: { label: 'PRIOR', note: 'Starting formula: no usable roll calls on this dimension' },
  imputed: { label: 'IMPUTED', note: 'No voting record: caucus estimate, adjusted for state' },
  override: { label: 'OVERRIDE', note: 'Hand-set from cited roll calls' },
}

const STOPS = [
  [-2, [25, 211, 255]],
  [-0.7, [32, 120, 150]],
  [0, [44, 54, 68]],
  [0.7, [190, 120, 30]],
  [2, [255, 176, 32]],
]

export function scoreColor(v) {
  if (v == null || Number.isNaN(v)) return '#3a4250'
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
  return 'rgb(255,176,32)'
}

export function probColor(p) {
  // 0 = Nay (red-violet), 0.5 = undecided (slate), 1 = Yea (green)
  if (p == null) return '#3a4250'
  const lerp = (a, b, t) => Math.round(a + (b - a) * t)
  const nay = [255, 77, 110]
  const mid = [52, 60, 74]
  const yea = [61, 255, 160]
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
  majority: 'SIMPLE MAJORITY',
  cloture: 'CLOTURE · 60',
  two_thirds: 'TWO-THIRDS',
}

export function thresholdNeed(threshold, voting) {
  if (threshold === 'cloture') return 60
  if (threshold === 'two_thirds') return Math.ceil((2 * voting) / 3)
  return Math.floor(voting / 2) + 1
}
