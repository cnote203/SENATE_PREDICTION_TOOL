import { useEffect, useMemo, useState } from 'react'
import { CAUCUS, SECTOR_SHORT, lastName, scoreColor } from '../util.js'

const TZ = 'America/New_York'
const LIVE_BEFORE_MS = 10 * 60 * 1000
const LIVE_AFTER_MS = 3 * 60 * 60 * 1000

const dayKey = (d) => d.toLocaleDateString('en-CA', { timeZone: TZ })
const dayLabel = (d) => d.toLocaleDateString('en-US', { timeZone: TZ, weekday: 'short', month: 'short', day: 'numeric' })
const timeLabel = (d) => d.toLocaleTimeString('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' })
const shortCommittee = (n) => n.replace(/^Senate (Select |Special )?Committee on /, '').replace(/^United States Senate /, '')

// Newer files carry `agenda` with links; older ones only `bills` and `nominations`.
const agendaOf = (h) => h.agenda ?? [...(h.bills ?? []), ...(h.nominations ?? [])].map((label) => ({ label, url: null }))

export function hearingState(h, now) {
  const start = new Date(h.start).getTime()
  if (h.status === 'Canceled' || h.status === 'Postponed') return h.status
  if (now >= start - LIVE_BEFORE_MS && now <= start + LIVE_AFTER_MS) return 'Live'
  if (now > start) return 'Held'
  return dayKey(new Date(start)) === dayKey(new Date(now)) ? 'Today' : 'Upcoming'
}

function countdown(ms) {
  if (ms <= 0) return 'NOW'
  const m = Math.floor(ms / 60000)
  const d = Math.floor(m / 1440)
  const hh = Math.floor((m % 1440) / 60)
  const mm = m % 60
  return d ? `${d}D ${hh}H` : hh ? `${hh}H ${mm}M` : `${mm}M`
}

export function useNow(step = 30000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), step)
    return () => clearInterval(t)
  }, [step])
  return now
}

function Monitor({ h, state, now }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => setArmed(false), [h?.id])
  if (!h) return <div className="monitor idle"><div className="mon-msg">Choose a hearing from the docket</div></div>

  const start = new Date(h.start).getTime()
  const links = [
    [h.links.committeeHearings ?? h.links.committee, 'Committee webcast', 'Official stream on the committee website'],
    [h.links.cspan, 'C-SPAN', 'Find C-SPAN coverage of this hearing'],
    [h.links.congress, 'Congress.gov', 'Notice, witnesses and documents'],
  ].filter(([u]) => u)

  return (
    <div className={`monitor st-${state.toLowerCase()}`}>
      <div className="mon-bar">
        <span className={`chip st-${state.toLowerCase()}`}>{state === 'Live' ? '● Live' : state}</span>
        <span>{shortCommittee(h.committees[0].name)}{h.committees[0].subName ? `, ${h.committees[0].subName}` : ''}</span>
        <span className="mon-clock">{state === 'Upcoming' || state === 'Today' ? `Gavel in ${countdown(start - now)}` : `${dayLabel(new Date(start))}, ${timeLabel(new Date(start))} ET`}</span>
      </div>
      <div className="mon-screen">
        {h.embed && armed ? (
          <iframe
            key={h.embed.url}
            src={h.embed.url}
            title={h.title}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <div className="mon-msg">
            {h.embed ? (
              <button className="mon-play" onClick={() => setArmed(true)}>▶ Play {h.embed.label}</button>
            ) : (
              <>
                <div className="mon-nofeed">No player for this hearing yet</div>
                <div className="mon-sub">{state === 'Live' ? 'It’s in session now. Open the official webcast below.' : state === 'Held' ? 'Archived video is on the committee site and C-SPAN.' : 'The committee webcast goes live at the gavel.'}</div>
              </>
            )}
            <div className="mon-links">
              {links.map(([u, l, t]) => <a key={l} href={u} target="_blank" rel="noopener noreferrer" title={t}>{l} ↗</a>)}
            </div>
          </div>
        )}
        <div className="mon-noise" aria-hidden="true" />
      </div>
      <div className="mon-attrib">
        {h.embed?.source === 'manual' && h.embed.url.includes('c-span.org')
          ? 'Video: C-SPAN. Coverage of federal government events, used for non-commercial purposes with attribution.'
          : 'Committee webcasts are produced by the Senate. C-SPAN coverage is credited to C-SPAN and opened on c-span.org.'}
      </div>
    </div>
  )
}

function Dais({ committeeId, senators, sector, dimension, onSelect }) {
  const members = senators
    .map((s) => ({ s, c: s.committees.find((c) => c.id === committeeId) }))
    .filter((x) => x.c)
  const rank = (t) => (/^Chair/.test(t) ? 0 : /Ranking|Vice/.test(t) ? 1 : 2)
  const side = (k) => members.filter((x) => x.s.caucus === k).sort((a, b) => rank(a.c.title) - rank(b.c.title) || a.s.seniority - b.s.seniority)
  if (!members.length) return <p className="muted">No projected members for this committee.</p>
  return (
    <div className="dais">
      {['D', 'R'].map((k) => (
        <div key={k} className="dais-side">
          <div className="dais-head" style={{ color: CAUCUS[k].color }}>{k === 'D' ? 'Democrats' : 'Republicans'} ({side(k).length})</div>
          {side(k).map(({ s, c }) => {
            const sc = s.scores[sector]?.[dimension]?.score
            return (
              <button key={s.id} className="dais-seat" onClick={() => onSelect(s.id)} title={c.title || 'Member'}>
                <i style={{ background: scoreColor(sc) }} />
                <span>{lastName(s.name)}</span>
                <small>{s.state}{c.title ? ` · ${c.title.replace('Ranking Member', 'RM').replace('Chairman', 'Chair').replace('Vice Chairman', 'Vice')}` : ''}</small>
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}

export default function Hearings({ hearings, senators, sector, dimension, meta, onSelect }) {
  const now = useNow()
  const [scope, setScope] = useState('sector')
  const [pick, setPick] = useState(null)
  const list = useMemo(() => (hearings?.hearings ?? []).slice().sort((a, b) => a.start.localeCompare(b.start)), [hearings])

  const shown = useMemo(() => list.filter((h) => scope === 'all' || h.sectors.includes(sector)), [list, scope, sector])
  const states = useMemo(() => Object.fromEntries(list.map((h) => [h.id, hearingState(h, now)])), [list, now])

  const auto = shown.find((h) => states[h.id] === 'Live')
    ?? shown.find((h) => states[h.id] === 'Today' || states[h.id] === 'Upcoming')
    ?? shown[shown.length - 1]
  const current = shown.find((h) => h.id === pick) ?? auto
  const mod = meta.modules.find((m) => m.id === sector)
  // Color the dais on the hearing's own sector, so a HELP hearing reads on a health dimension.
  const daisSector = !current || current.sectors.includes(sector) ? sector : current.sectors[0] ?? sector
  const daisMod = meta.modules.find((m) => m.id === daisSector)
  const daisDim = daisSector === sector ? dimension : (daisMod.dimensions.find((d) => d.calibrated) ?? daisMod.dimensions[0]).id

  if (!hearings) {
    return (
      <section className="hearings"><div className="panel">
        <h3>No hearing schedule yet</h3>
        <p className="muted">No hearings.json yet. Run <code>python scripts\fetch_hearings.py</code> with CONGRESS_API_KEY set, or add the key as a repository secret so the Pages workflow refreshes it.</p>
      </div></section>
    )
  }

  const groups = []
  for (const h of shown) {
    const d = new Date(h.start)
    const k = dayKey(d)
    if (!groups.length || groups[groups.length - 1].k !== k) groups.push({ k, label: dayLabel(d), items: [] })
    groups[groups.length - 1].items.push(h)
  }
  const liveCount = shown.filter((h) => states[h.id] === 'Live').length

  return (
    <section className="hearings">
      <div className="docket panel">
        <div className="dk-head">
          <div>
            <div className="kicker">{hearings.window.from} to {hearings.window.to}</div>
            <h3>{scope === 'all' ? 'Every Senate committee' : `${mod.label} committees`}</h3>
          </div>
          <div className="dk-scope">
            {[['sector', SECTOR_SHORT[sector] ?? 'This area'], ['all', 'All']].map(([k, l]) => (
              <button key={k} className={scope === k ? 'on' : ''} onClick={() => setScope(k)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="dk-stats">
          <span><b>{shown.length}</b> hearings</span>
          <span className={liveCount ? 'live' : ''}><b>{liveCount}</b> live</span>
          <span><b>{shown.filter((h) => ['Today', 'Upcoming'].includes(states[h.id])).length}</b> ahead</span>
        </div>
        <div className="dk-list">
          {!groups.length && <p className="muted">No hearings for these committees in the window. Try ALL.</p>}
          {groups.map((g) => (
            <div key={g.k}>
              <div className="dk-day">{g.label}</div>
              {g.items.map((h) => {
                const st = states[h.id]
                return (
                  <button key={h.id} className={`dk-row st-${st.toLowerCase()} ${current?.id === h.id ? 'sel' : ''}`} onClick={() => setPick(h.id)}>
                    <span className="dk-time">{timeLabel(new Date(h.start))}</span>
                    <span className="dk-body">
                      <span className="dk-com">{shortCommittee(h.committees[0].name)}{h.committees[0].sub ? ', subcommittee' : ''}</span>
                      <span className="dk-title">{h.title}</span>
                      <span className="dk-tags">
                        <span className={`chip st-${st.toLowerCase()}`}>{st === 'Live' ? '● Live' : st}</span>
                        {h.embed && <span className="chip feed">Player</span>}
                        {h.sectors.map((s) => <span key={s} className="chip sec">{SECTOR_SHORT[s] ?? s}</span>)}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          ))}
        </div>
        <div className="dk-foot">Schedule from Congress.gov, refreshed {hearings.generated.replace('T', ' ').replace('Z', ' UTC')}. Times are Eastern.</div>
      </div>

      <div className="watch">
        <Monitor h={current} state={current ? states[current.id] : 'IDLE'} now={now} />
        {current && (
          <div className="panel hearing-detail">
            <h2>{current.title}</h2>
            <div className="hd-meta">
              <span>{dayLabel(new Date(current.start))}, {timeLabel(new Date(current.start))} ET</span>
              {current.location && <span>{current.location}</span>}
              {current.committees.map((c) => <span key={c.id + (c.sub ?? '')}>{shortCommittee(c.name)}{c.subName ? ` › ${c.subName}` : ''}</span>)}
            </div>
            <div className="hd-cols">
              <div>
                <h3>On the dais <small>projected 120th membership, colored by {daisMod.dimensions.find((d) => d.id === daisDim)?.label ?? 'score'}</small></h3>
                <Dais committeeId={current.committees[0].id} senators={senators} sector={daisSector} dimension={daisDim} onSelect={onSelect} />
              </div>
              <div>
                <h3>Witnesses</h3>
                {current.witnesses.length ? current.witnesses.map((w, i) => (
                  <div key={i} className="witness"><b>{w.name}</b><span>{[w.position, w.organization].filter(Boolean).join(', ')}</span></div>
                )) : <p className="muted">Not yet posted.</p>}
                {agendaOf(current).length > 0 && (
                  <>
                    <h3>On the agenda <small>bill text from GovInfo</small></h3>
                    <div className="agenda">{agendaOf(current).map((a) => a.url
                      ? <a key={a.label} className="chip" href={a.url} target="_blank" rel="noopener noreferrer" title={a.kind === 'bill' ? 'Latest bill text (GovInfo)' : 'Nomination (Congress.gov)'}>{a.label} ↗</a>
                      : <span key={a.label} className="chip">{a.label}</span>)}</div>
                  </>
                )}
                {(current.transcripts ?? []).length > 0 && (
                  <>
                    <h3>Transcript</h3>
                    {current.transcripts.map((t) => <a key={t.jacket} className="vid" href={t.url} target="_blank" rel="noopener noreferrer">Printed hearing {t.jacket} (GovInfo) ↗</a>)}
                  </>
                )}
                {current.videos.length > 0 && (
                  <>
                    <h3>Video</h3>
                    {current.videos.map((v) => <a key={v.url} className="vid" href={v.url} target="_blank" rel="noopener noreferrer">{v.name} ↗</a>)}
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
