import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import Hemicycle from './components/Hemicycle.jsx'
import { webglAvailable } from './components/webgl.js'

// three.js is large, so the 3D chamber loads after the page is up.
const Chamber3D = lazy(() => import('./components/Chamber3D.jsx'))
import { Briefing, Dossier } from './components/Panels.jsx'
import { RollCallPanel, useRollCall } from './components/RollCall.jsx'
import Timeline from './components/Timeline.jsx'
import Hearings, { hearingState, useNow } from './components/Hearings.jsx'
import { CAUCUS, SECTOR_SHORT, SOURCE, dimensionIndex, pct, probColor, scoreColor } from './util.js'

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
  const [sector, setSector] = useState('foreign_policy')
  const [dimension, setDimension] = useState('arms_sales_oversight')
  const [colorMode, setColorMode] = useState('score')
  const [selected, setSelected] = useState(null)
  const [measureId, setMeasureId] = useState('foreign_policy:israel_arms_disapproval')
  const [president, setPresident] = useState('R')
  const [branch, setBranch] = useState('D')
  const [hearings, setHearings] = useState(null)
  const [view, setView] = useState(() => (webglAvailable() ? '3d' : 'plan'))
  const now = useNow(60000)

  useEffect(() => {
    Promise.all(['senators.json', 'measures.json', 'timeline.json', 'meta.json'].map(load))
      .then(([senators, measures, timeline, meta]) => setData({ senators, measures, timeline, meta }))
      .catch((e) => setError(String(e)))
    load('hearings.json').then(setHearings).catch(() => setHearings(null))
  }, [])

  const dims = useMemo(() => (data ? dimensionIndex(data.meta) : {}), [data])
  const sectorMeasures = data ? data.measures.filter((m) => (m.module ?? 'foreign_policy') === sector) : []
  const measure = sectorMeasures.find((m) => m.id === measureId) ?? sectorMeasures[0]
  const yeaProb = measure?.byPresident[president].senatorYea ?? {}
  const roll = useRollCall(data?.senators ?? [], yeaProb)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setSelected(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const switchSector = (id) => {
    if (!data || id === sector) return
    const mod = data.meta.modules.find((m) => m.id === id)
    setSector(id)
    setDimension(mod.dimensions.find((d) => d.calibrated)?.id ?? mod.dimensions[0].id)
    const first = data.measures.find((m) => m.module === id)
    if (first) setMeasureId(first.id)
    roll.reset()
  }

  const score = (s) => s.scores[sector]?.[dimension]
  const order = useMemo(() => {
    if (!data) return []
    const key = mode === 'rollcall'
      ? (s) => yeaProb[s.id] ?? 0.5
      : (s) => s.scores[sector]?.[dimension]?.score ?? 0
    return data.senators.slice().sort((a, b) => key(a) - key(b) || a.name.localeCompare(b.name)).map((s) => s.id)
  }, [data, dimension, mode, yeaProb, sector])

  if (error) return <div className="boot err">The model data didn’t load ({error}). Run scripts/export_web.py and rebuild.</div>
  if (!data) return <div className="boot">Opening the chamber…</div>

  const { senators, measures, timeline, meta } = data
  const liveNow = (hearings?.hearings ?? []).filter((h) => hearingState(h, now) === 'Live')
  const mod = meta.modules.find((m) => m.id === sector)
  const dim = dims[dimension]
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
      const sd = score(s)?.sd ?? 1
      const a = Math.max(0.12, Math.min(1, 1 - (sd - 0.15) / 0.85))
      return `rgba(232,246,255,${a.toFixed(2)})`
    }
  } else if (colorMode === 'evidence') {
    colorOf = (s) => SOURCE_COLOR[score(s)?.source] ?? '#3a4250'
  } else {
    colorOf = (s) => scoreColor(score(s)?.score)
  }

  const r = measure?.byPresident[president]
  const ticker = measures.flatMap((m) => ['R', 'D'].map((p) =>
    `${m.name.replace('Joint resolution of disapproval: ', 'Disapproving ')}, ${p === 'R' ? 'Republican' : 'Democratic'} president: passes the Senate ${pct(m.byPresident[p].pPassSenate)}, becomes law ${pct(m.byPresident[p].pEnacted, 1)}${m.byPresident[p].calibrated ? '' : ' (illustrative)'}`))

  const ticker2 = [...liveNow.map((h) => `Live now in ${h.committees[0].name.replace('Senate Committee on ', '')}: ${h.title.slice(0, 90)}`), ...ticker]
  const tally = Object.values(roll.votes)
  const center = mode === 'rollcall' ? (
    <>
      <text x="450" y="385" className="c-big">
        <tspan className="c-y">{tally.filter((v) => v === 'Y').length}</tspan>
        <tspan dx="18" className="c-sep">—</tspan>
        <tspan dx="18" className="c-n">{tally.filter((v) => v === 'N').length}</tspan>
      </text>
      <text x="450" y="412" className="c-small">{tally.length ? 'Yea to nay' : `${pct(r?.pPassSenate, 1)} chance it passes the Senate`}</text>
      <text x="450" y="432" className="c-tiny">Seated from likely nay to likely yea</text>
    </>
  ) : (
    <>
      <text x="450" y="385" className="c-big">
        <tspan className="c-d">{dCount}</tspan>
        <tspan dx="18" className="c-sep">|</tspan>
        <tspan dx="18" className="c-r">{rCount}</tspan>
      </text>
      <text x="450" y="412" className="c-small">{dim.label}</text>
      <text x="450" y="432" className="c-tiny">Seated from {dim.lowTag.toLowerCase()} to {dim.highTag.toLowerCase()}</text>
    </>
  )

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <svg className="mark" viewBox="0 0 40 24" aria-hidden="true">
            {[8, 13, 18].map((r, i) => Array.from({ length: 5 + i * 2 }, (_, j) => {
              const a = Math.PI - (Math.PI * (j + 0.5)) / (5 + i * 2)
              return <circle key={`${i}-${j}`} cx={20 + r * Math.cos(a)} cy={22 - r * Math.sin(a)} r="1.35" />
            }))}
            <rect x="16" y="20.5" width="8" height="2.5" rx="0.6" />
          </svg>
          <div>
            <h1>Senate Situation Board</h1>
            <div className="sub">The 120th Congress, projected across {meta.modules.length} policy areas. Model run {meta.generated}.</div>
          </div>
        </div>
        <nav className="modes">
          {[['chamber', 'Chamber'], ['rollcall', 'Roll call'], ['timeline', '2027–2032'], ['hearings', 'Hearings']].map(([k, l]) => (
            <button key={k} className={mode === k ? 'on' : ''} onClick={() => { setMode(k); roll.reset() }}>
              {k === 'hearings' && liveNow.length > 0 && <span className="live-dot" title={`${liveNow.length} live now`} />}{l}
            </button>
          ))}
        </nav>
      </header>

      <nav className="sectors" aria-label="Policy sector">
        {meta.modules.map((m) => {
          const fitted = m.dimensions.filter((d) => d.calibrated).length
          return (
            <button key={m.id} className={sector === m.id ? 'on' : ''} onClick={() => switchSector(m.id)}>
              <span className="s-name">{SECTOR_SHORT[m.id] ?? m.label}</span>
              <span className="s-meta">{fitted} of {m.dimensions.length} fitted to votes</span>
            </button>
          )
        })}
      </nav>

      <div className="ticker" aria-hidden="true">
        <div className="ticker-track">{[...ticker2, ...ticker2].map((t, i) => <span key={i}>{t}</span>)}</div>
      </div>

      {mode === 'hearings' ? (
        <>
          <Hearings hearings={hearings} senators={senators} sector={sector} dimension={dimension} meta={meta} onSelect={setSelected} />
          {sel && (
            <div className="drawer" onClick={() => setSelected(null)}>
              <div onClick={(e) => e.stopPropagation()}>
                <Dossier s={sel} sector={sector} dimension={dimension} onClose={() => setSelected(null)} meta={meta} onSector={switchSector} />
              </div>
            </div>
          )}
        </>
      ) : mode === 'timeline' ? (
        <Timeline timeline={timeline} measures={measures} branch={branch} setBranch={setBranch} sector={sector} meta={meta} />
      ) : (
        <main className="grid">
          <section className="stage">
            {mode === 'chamber' && (
              <div className="controls">
                <div className="dims">
                  {mod.dimensions.map((d) => (
                    <button key={d.id} className={dimension === d.id ? 'on' : ''} onClick={() => setDimension(d.id)}>
                      <span className="d-short">{d.short}</span>{d.label}
                      {!d.calibrated && <span className="d-flag" title="Not calibrated to roll calls">◌</span>}
                    </button>
                  ))}
                </div>
                <div className="colormodes">
                  <span>Color by</span>
                  {['score', 'caucus', 'uncertainty', 'evidence'].map((c) => (
                    <button key={c} className={colorMode === c ? 'on' : ''} onClick={() => setColorMode(c)}>{c.charAt(0).toUpperCase() + c.slice(1)}</button>
                  ))}
                </div>
              </div>
            )}
            <div className="viewswitch" role="group" aria-label="Chamber view">
              {[['3d', 'Chamber'], ['plan', 'Floor plan']].map(([k, l]) => (
                <button key={k} className={view === k ? 'on' : ''} aria-pressed={view === k} onClick={() => setView(k)}>{l}</button>
              ))}
            </div>
            {view === '3d'
              ? (
                <Suspense fallback={<div className="chamber-loading">Setting out the desks…</div>}>
                  <Chamber3D senators={senators} order={order} colorOf={colorOf} selected={selected} onSelect={setSelected} center={center} />
                </Suspense>
              )
              : <Hemicycle senators={senators} order={order} colorOf={colorOf} selected={selected} onSelect={setSelected} center={center} />}
            {mode === 'chamber' && colorMode === 'score' && (
              <div className="legend">
                <span>−2 {dim.lowTag.charAt(0) + dim.lowTag.slice(1).toLowerCase()}</span>
                <div className="grad" />
                <span>{dim.highTag.charAt(0) + dim.highTag.slice(1).toLowerCase()} +2</span>
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
              <div className="legend"><span>Uncertain</span><div className="grad mono" /><span>Confident</span></div>
            )}
            {mode === 'rollcall' && (
              <div className="legend"><span>Nay</span><div className="grad prob" /><span>Yea</span></div>
            )}
          </section>

          {sel ? (
            <Dossier s={sel} sector={sector} dimension={mode === 'rollcall' ? measure?.dimension : dimension}
              onClose={() => setSelected(null)} meta={meta} onSector={switchSector} />
          ) : mode === 'rollcall' && measure ? (
            <RollCallPanel measures={sectorMeasures} measureId={measure.id} setMeasureId={setMeasureId} president={president}
              setPresident={setPresident} senators={senators} roll={roll} onSelect={setSelected} dims={dims} sectorLabel={mod.label} />
          ) : (
            <Briefing senators={senators} sector={sector} dimension={dimension} meta={meta} onSelect={setSelected} />
          )}
        </main>
      )}

      <footer className="foot">
        <span>Model projection, not a forecast of record. Scores −2…+2 from Senate roll calls (Voteview), DW-NOMINATE, OpenFEC PAC data and hand-checked overrides.</span>
        <span>{meta.sources.map((s) => s.name).join(' · ')}{mode === 'hearings' ? ' · Congress.gov committee meetings · Video © C-SPAN / U.S. Senate' : ''}</span>
      </footer>
    </div>
  )
}
