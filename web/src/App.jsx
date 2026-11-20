import { useEffect, useMemo, useState } from 'react'
import Hemicycle from './components/Hemicycle.jsx'
import { Briefing, Dossier } from './components/Panels.jsx'
import { RollCallPanel, useRollCall } from './components/RollCall.jsx'
import Timeline from './components/Timeline.jsx'
import { CAUCUS, DIMENSIONS, SOURCE, pct, probColor, scoreColor } from './util.js'

const BASE = import.meta.env.BASE_URL
const load = (f) => fetch(`${BASE}data/${f}`).then((r) => {
  if (!r.ok) throw new Error(`${f}: ${r.status}`)
  return r.json()
})

const SOURCE_COLOR = {
  votes: '#3dffa0', override: '#ffb020', fitted: '#7aa7ff', 'fitted+donors': '#b07cff', imputed: '#ff6b8a', formula: '#5a6578',
}

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('chamber')
  const [dimension, setDimension] = useState('arms_sales_oversight')
  const [colorMode, setColorMode] = useState('score')
  const [selected, setSelected] = useState(null)
  const [measureId, setMeasureId] = useState('israel_arms_disapproval')
  const [president, setPresident] = useState('R')
  const [branch, setBranch] = useState('D')

  useEffect(() => {
    Promise.all(['senators.json', 'measures.json', 'timeline.json', 'meta.json'].map(load))
      .then(([senators, measures, timeline, meta]) => setData({ senators, measures, timeline, meta }))
      .catch((e) => setError(String(e)))
  }, [])

  const measure = data?.measures.find((m) => m.id === measureId)
  const yeaProb = measure?.byPresident[president].senatorYea ?? {}
  const roll = useRollCall(data?.senators ?? [], yeaProb)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setSelected(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const order = useMemo(() => {
    if (!data) return []
    const key = mode === 'rollcall'
      ? (s) => yeaProb[s.id] ?? 0.5
      : (s) => s.scores[dimension].score ?? 0
    return data.senators.slice().sort((a, b) => key(a) - key(b) || a.name.localeCompare(b.name)).map((s) => s.id)
  }, [data, dimension, mode, yeaProb])

  if (error) return <div className="boot err">DATA LINK FAILED · {error}<br />Run scripts/export_web.py and rebuild.</div>
  if (!data) return <div className="boot">ESTABLISHING DATA LINK<span className="blink">_</span></div>

  const { senators, measures, timeline, meta } = data
  const sel = senators.find((s) => s.id === selected)
  const dCount = senators.filter((s) => s.caucus === 'D').length
  const rCount = senators.length - dCount

  let colorOf
  if (mode === 'rollcall') {
    const voted = roll.votes
    const any = Object.keys(voted).length > 0
    colorOf = (s) => {
      if (!any) return probColor(yeaProb[s.id])
      const v = voted[s.id]
      if (!v) return '#1a2230'
      return v === 'Y' ? '#3dffa0' : v === 'N' ? '#ff4d6e' : '#566070'
    }
  } else if (colorMode === 'caucus') {
    colorOf = (s) => CAUCUS[s.caucus].color
  } else if (colorMode === 'uncertainty') {
    colorOf = (s) => {
      const sd = s.scores[dimension].sd ?? 1
      const a = Math.max(0.12, Math.min(1, 1 - (sd - 0.15) / 0.85))
      return `rgba(232,246,255,${a.toFixed(2)})`
    }
  } else if (colorMode === 'evidence') {
    colorOf = (s) => SOURCE_COLOR[s.scores[dimension].source] ?? '#3a4250'
  } else {
    colorOf = (s) => scoreColor(s.scores[dimension].score)
  }

  const r = measure.byPresident[president]
  const ticker = measures.flatMap((m) => ['R', 'D'].map((p) =>
    `${m.name.replace('Joint resolution of disapproval: ', '').toUpperCase()} · ${p === 'R' ? 'GOP' : 'DEM'} WHITE HOUSE · SENATE ${pct(m.byPresident[p].pPassSenate)} · LAW ${pct(m.byPresident[p].pEnacted, 1)}`))

  const tally = Object.values(roll.votes)
  const center = mode === 'rollcall' ? (
    <>
      <text x="450" y="385" className="c-big">
        <tspan className="c-y">{tally.filter((v) => v === 'Y').length}</tspan>
        <tspan dx="18" className="c-sep">—</tspan>
        <tspan dx="18" className="c-n">{tally.filter((v) => v === 'N').length}</tspan>
      </text>
      <text x="450" y="412" className="c-small">{tally.length ? 'YEA — NAY' : `P(PASS SENATE) ${pct(r.pPassSenate, 1)}`}</text>
      <text x="450" y="432" className="c-tiny">← NAY · ORDERED BY YEA ODDS · YEA →</text>
    </>
  ) : (
    <>
      <text x="450" y="385" className="c-big">
        <tspan className="c-d">{dCount}</tspan>
        <tspan dx="18" className="c-sep">|</tspan>
        <tspan dx="18" className="c-r">{rCount}</tspan>
      </text>
      <text x="450" y="412" className="c-small">{DIMENSIONS[dimension].label.toUpperCase()}</text>
      <text x="450" y="432" className="c-tiny">← {DIMENSIONS[dimension].lowTag} · ORDERED BY SCORE · {DIMENSIONS[dimension].highTag} →</text>
    </>
  )

  return (
    <div className="app">
      <div className="scanlines" aria-hidden="true" />
      <header className="top">
        <div className="brand">
          <div className="sigil" aria-hidden="true"><span /><span /><span /></div>
          <div>
            <h1>SENATE SITUATION BOARD</h1>
            <div className="sub">FOREIGN POLICY · 120TH CONGRESS PROJECTION · MODEL OUTPUT {meta.generated}</div>
          </div>
        </div>
        <nav className="modes">
          {[['chamber', 'CHAMBER'], ['rollcall', 'ROLL CALL'], ['timeline', '2027–2032']].map(([k, l]) => (
            <button key={k} className={mode === k ? 'on' : ''} onClick={() => { setMode(k); roll.reset() }}>{l}</button>
          ))}
        </nav>
      </header>

      <div className="ticker" aria-hidden="true">
        <div className="ticker-track">{[...ticker, ...ticker].map((t, i) => <span key={i}>{t}</span>)}</div>
      </div>

      {mode === 'timeline' ? (
        <Timeline timeline={timeline} measures={measures} branch={branch} setBranch={setBranch} />
      ) : (
        <main className="grid">
          <section className="stage">
            {mode === 'chamber' && (
              <div className="controls">
                <div className="dims">
                  {Object.entries(DIMENSIONS).map(([k, d]) => (
                    <button key={k} className={dimension === k ? 'on' : ''} onClick={() => setDimension(k)}>
                      <span className="d-short">{d.short}</span>{d.label}
                    </button>
                  ))}
                </div>
                <div className="colormodes">
                  <span>COLOR</span>
                  {['score', 'caucus', 'uncertainty', 'evidence'].map((c) => (
                    <button key={c} className={colorMode === c ? 'on' : ''} onClick={() => setColorMode(c)}>{c.toUpperCase()}</button>
                  ))}
                </div>
              </div>
            )}
            <Hemicycle
              senators={senators}
              order={order}
              colorOf={colorOf}
              selected={selected}
              onSelect={setSelected}
              center={center}
            />
            {mode === 'chamber' && colorMode === 'score' && (
              <div className="legend">
                <span>−2 {DIMENSIONS[dimension].lowTag}</span>
                <div className="grad" />
                <span>{DIMENSIONS[dimension].highTag} +2</span>
              </div>
            )}
            {mode === 'chamber' && colorMode === 'evidence' && (
              <div className="legend chips">
                {Object.entries(SOURCE_COLOR).map(([k, c]) => (
                  <span key={k} title={SOURCE[k].note}><i style={{ background: c }} />{SOURCE[k].label}</span>
                ))}
              </div>
            )}
            {mode === 'chamber' && colorMode === 'uncertainty' && (
              <div className="legend"><span>UNCERTAIN</span><div className="grad mono" /><span>CONFIDENT</span></div>
            )}
            {mode === 'rollcall' && (
              <div className="legend"><span>NAY</span><div className="grad prob" /><span>YEA</span></div>
            )}
          </section>

          {sel ? (
            <Dossier s={sel} dimension={mode === 'rollcall' ? measure.dimension : dimension} onClose={() => setSelected(null)} meta={meta} />
          ) : mode === 'rollcall' ? (
            <RollCallPanel measures={measures} measureId={measureId} setMeasureId={setMeasureId} president={president}
              setPresident={setPresident} senators={senators} roll={roll} onSelect={setSelected} />
          ) : (
            <Briefing senators={senators} dimension={dimension} meta={meta} onSelect={setSelected} colorMode={colorMode} />
          )}
        </main>
      )}

      <footer className="foot">
        <span>Model projection, not a forecast of record. Scores −2…+2 from Senate roll calls (Voteview), DW-NOMINATE, OpenFEC PAC data and hand-checked overrides.</span>
        <span>{meta.sources.map((s) => s.name).join(' · ')}</span>
      </footer>
    </div>
  )
}
