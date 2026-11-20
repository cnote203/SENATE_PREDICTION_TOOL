import { CAUCUS, lastName, pct } from '../util.js'

const YEARS = { 120: '2027–28', 121: '2029–30', 122: '2031–32' }
const EVENT = { 120: 'CURRENT SENATE', 121: 'AFTER 2028 · CLASS 3', 122: 'AFTER 2030 MIDTERM · CLASS 1' }
const POSTS = [
  ['SSFR_chair', 'Foreign Relations'],
  ['SSAS_chair', 'Armed Services'],
  ['SSAP_chair', 'Appropriations'],
  ['SLIN_chair', 'Intelligence'],
]

const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1)

function SeatStrip({ mean, p10, p90 }) {
  const cells = Array.from({ length: 100 }, (_, i) => {
    const n = i + 1
    let cls = 'r'
    if (n <= Math.round(p10)) cls = 'd'
    else if (n <= Math.round(mean)) cls = 'd-lik'
    else if (n <= Math.round(p90)) cls = 'r-lik'
    return <span key={i} className={`cell ${cls} ${n === 50 ? 'half' : ''}`} />
  })
  return <div className="strip">{cells}</div>
}

export default function Timeline({ timeline, measures, branch, setBranch }) {
  const t = timeline[branch]
  if (!t) {
    return <div className="panel"><p className="muted">No multi-cycle results exported yet. Run run_multicycle.py for both branches, then export_web.py.</p></div>
  }
  const mname = Object.fromEntries(measures.map((m) => [m.id, m.name]))
  return (
    <section className="timeline">
      <div className="tl-head">
        <div>
          <div className="kicker">PROJECTION · {t.measures[0]?.runs ?? '—'} SIMULATED ELECTION PATHS PER BRANCH</div>
          <h2>2027 → 2032</h2>
        </div>
        <div className="wh">
          <span>2028 WINNER</span>
          {['D', 'R'].map((p) => (
            <button key={p} className={`whbtn wh-${p} ${branch === p ? 'on' : ''}`} onClick={() => setBranch(p)}>
              {p === 'D' ? 'DEMOCRAT' : 'REPUBLICAN'}
            </button>
          ))}
        </div>
      </div>
      <div className="tl-cols">
        {t.congresses.map((c) => {
          const n = c.congress
          const pres = n === 120 ? 'R' : branch
          return (
            <div key={n} className="tl-col">
              <div className="tl-congress">{n}TH CONGRESS</div>
              <div className="tl-years">{YEARS[n]}</div>
              <div className="tl-event">{EVENT[n]}</div>
              <div className="tl-big">
                <div><b style={{ color: CAUCUS.D.color }}>{c.d_seats_mean.toFixed(1)}</b><span>D SEATS (MEAN)</span></div>
                <div><b>{pct(c.p_d_senate)}</b><span>D CONTROL</span></div>
                <div><b style={{ color: CAUCUS[pres].color }}>{pres}</b><span>WHITE HOUSE</span></div>
              </div>
              <SeatStrip mean={c.d_seats_mean} p10={c.d_seats_p10} p90={c.d_seats_p90} />
              <div className="tl-range">10–90% range: {c.d_seats_p10.toFixed(0)}–{c.d_seats_p90.toFixed(0)} D seats{n > 120 ? ` · ${c.new_senators_mean.toFixed(1)} new senators` : ''}</div>

              <h4>Measures</h4>
              {t.measures.filter((m) => m.congress === n).map((m) => (
                <div key={m.measure} className="tl-measure">
                  <span className="tm-name">{cap(mname[m.measure]?.replace('Joint resolution of disapproval: ', '') ?? m.measure)}</span>
                  <span className="tm-bar"><span style={{ width: `${m.p_passes_senate * 100}%` }} /></span>
                  <span className="tm-p">{pct(m.p_passes_senate)}</span>
                  <span className="tm-y">{m.yeas_median == null ? '—' : Math.round(m.yeas_median)} yeas</span>
                </div>
              ))}

              <h4>Chairs</h4>
              {POSTS.map(([post, label]) => {
                const l = t.leadership.find((x) => x.congress === n && x.post === post)
                const top = l ? Object.entries(l.holders) : []
                return (
                  <div key={post} className="tl-chair">
                    <span className="tc-label">{label}</span>
                    <span className="tc-who">
                      {top.map(([name, p], i) => (
                        <span key={name} className={i === 0 ? 'lead' : 'alt'}>{lastName(name)} {pct(p)}</span>
                      ))}
                    </span>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
      <p className="muted small tl-foot">
        Each path draws retirements, Senate races (state lean from 2024 + national environment + incumbency) and, after 2028,
        a midterm swing against the President’s party. The 2026 environment is estimated from which party won each 2026 seat.
        Election settings are judgment calls, not yet fitted to past results.
      </p>
    </section>
  )
}
