import { useEffect, useRef, useState } from 'react'
import { CAUCUS, DIMENSIONS, THRESHOLD_LABEL, lastName, pct, thresholdNeed } from '../util.js'

const ATTENDANCE = 0.97
const STEP_MS = 55

// Draws one roll call from each senator's Yea probability and reveals it in
// alphabetical order, like the clerk calling the roll.
export function useRollCall(senators, yeaProb) {
  const [votes, setVotes] = useState({})
  const [running, setRunning] = useState(false)
  const timer = useRef(null)

  const reset = () => {
    clearInterval(timer.current)
    setRunning(false)
    setVotes({})
  }

  const run = () => {
    clearInterval(timer.current)
    const order = senators.slice().sort((a, b) => lastName(a.name).localeCompare(lastName(b.name)))
    const draw = order.map((s) => {
      if (Math.random() > ATTENDANCE) return [s.id, 'NV']
      return [s.id, Math.random() < (yeaProb[s.id] ?? 0.5) ? 'Y' : 'N']
    })
    setVotes({})
    setRunning(true)
    let i = 0
    timer.current = setInterval(() => {
      i += 1
      setVotes(Object.fromEntries(draw.slice(0, i)))
      if (i >= draw.length) {
        clearInterval(timer.current)
        setRunning(false)
      }
    }, STEP_MS)
  }

  useEffect(() => () => clearInterval(timer.current), [])
  return { votes, running, run, reset }
}

function Histogram({ hist, need, mark }) {
  const W = 360
  const H = 90
  const max = Math.max(...hist)
  const bw = W / hist.length
  return (
    <svg viewBox={`0 0 ${W} ${H + 16}`} className="hist" aria-label="Distribution of Yea votes across simulations">
      {hist.map((c, i) => (
        <rect key={i} x={i * bw} y={H - (c / max) * H} width={Math.max(bw - 0.6, 0.5)} height={(c / max) * H}
          className={i >= need ? 'pass' : 'fail'} />
      ))}
      <line x1={need * bw} x2={need * bw} y1={0} y2={H} className="need" />
      <text x={need * bw + 4} y={10} className="need-l">{need} NEEDED</text>
      {mark != null && <line x1={mark * bw + bw / 2} x2={mark * bw + bw / 2} y1={0} y2={H} className="mark" />}
      {[0, 25, 50, 75, 100].map((t) => (
        <text key={t} x={t * bw} y={H + 13} className="axis">{t}</text>
      ))}
    </svg>
  )
}

export function RollCallPanel({ measures, measureId, setMeasureId, president, setPresident, senators, roll, onSelect }) {
  const m = measures.find((x) => x.id === measureId)
  const r = m.byPresident[president]
  const final = m.stages[m.stages.length - 1]
  const st = r.stages[final.name]
  const tally = Object.values(roll.votes)
  const yeas = tally.filter((v) => v === 'Y').length
  const nays = tally.filter((v) => v === 'N').length
  const done = tally.length === senators.length && !roll.running
  const need = thresholdNeed(final.threshold, yeas + nays || 97)
  const tiePasses = m.presidentPosition === 'support'
  const passed = final.threshold === 'majority' ? yeas > nays || (yeas === nays && tiePasses) : yeas >= need
  const yeaLabel = m.plusSide === 'Yea' ? DIMENSIONS[m.dimension].highTag : DIMENSIONS[m.dimension].lowTag

  return (
    <aside className="panel rollcall">
      <div className="kicker">ROLL CALL SIMULATOR · 120TH CONGRESS</div>
      <div className="measure-list">
        {measures.map((x) => (
          <button key={x.id} className={`measure ${x.id === measureId ? 'on' : ''}`} onClick={() => { setMeasureId(x.id); roll.reset() }}>
            <span className="mname">{x.name}</span>
            <span className="mdim">{DIMENSIONS[x.dimension].label} · Yea = {x.plusSide === 'Yea' ? DIMENSIONS[x.dimension].highTag : DIMENSIONS[x.dimension].lowTag}</span>
          </button>
        ))}
      </div>

      <div className="wh">
        <span>WHITE HOUSE</span>
        {['R', 'D'].map((p) => (
          <button key={p} className={`whbtn wh-${p} ${president === p ? 'on' : ''}`} onClick={() => { setPresident(p); roll.reset() }}>
            {p === 'R' ? 'REPUBLICAN' : 'DEMOCRATIC'}
          </button>
        ))}
      </div>

      <div className="odds">
        {m.stages.map((s) => (
          <div key={s.name}>
            <b>{pct(r.stages[s.name].p_pass_cumulative, 1)}</b>
            <span>{s.name.toUpperCase()} · {THRESHOLD_LABEL[s.threshold]}</span>
          </div>
        ))}
        <div>
          <b>{pct(r.pEnacted, r.pEnacted < 0.01 ? 2 : 1)}</b>
          <span>BECOMES LAW{m.vetoPossible ? ' · AFTER VETO' : ''}</span>
        </div>
      </div>

      <button className="run" onClick={roll.run} disabled={roll.running}>
        {roll.running ? 'CALLING THE ROLL…' : done ? 'CALL THE ROLL AGAIN' : 'CALL THE ROLL'}
      </button>

      <div className={`tally ${done ? (passed ? 'passed' : 'failed') : ''}`}>
        <div className="t-y"><b>{yeas}</b><span>YEA</span></div>
        <div className="t-n"><b>{nays}</b><span>NAY</span></div>
        <div className="t-v"><b>{tally.filter((v) => v === 'NV').length}</b><span>NOT VOTING</span></div>
        <div className="verdict">{done ? (passed ? 'AGREED TO' : 'REJECTED') : roll.running ? `${tally.length}/100` : 'STANDING BY'}</div>
      </div>

      <h3>Model distribution <small>{final.name} · Yea counts across simulations</small></h3>
      <Histogram hist={st.yeas_hist} need={thresholdNeed(final.threshold, 97)} mark={done ? yeas : null} />
      <p className="muted small">
        Median {st.yeas_median} yeas (10–90%: {st.yeas_p10_p90[0]}–{st.yeas_p10_p90[1]}). A Yea is a vote to {yeaLabel.toLowerCase()}.
        {m.vetoPossible && r.defectorsNeeded != null && ` Overriding a veto needs ${r.defectorsNeeded} senators from the President's party at full attendance.`}
        {!r.gammaIdentified && r.calibrated && president === 'D' && ' Only Trump-era votes exist for this dimension, so the Democratic White House case is an extrapolation.'}
      </p>

      <h3>Most often pivotal</h3>
      <ul className="pivots">
        {r.pivotal.map((p) => {
          const s = senators.find((x) => x.name === p.name)
          return (
            <li key={p.name} onClick={() => s && onSelect(s.id)}>
              <span className="dot" style={{ background: CAUCUS[p.caucus].color }} />
              <span className="pname">{p.name}</span>
              <span className="pval">{pct(p.share)}</span>
            </li>
          )
        })}
      </ul>
      {m.notes && <p className="muted small">{m.notes}</p>}
    </aside>
  )
}
