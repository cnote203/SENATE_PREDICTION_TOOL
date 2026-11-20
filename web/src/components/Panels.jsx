import { CAUCUS, DIMENSIONS, SOURCE, fmtScore, money, scoreColor } from '../util.js'

export function ScoreBar({ score, sd, source, compact }) {
  const x = (v) => ((Math.max(-2, Math.min(2, v)) + 2) / 4) * 100
  const lo = score == null ? 0 : x(score - (sd ?? 0))
  const hi = score == null ? 0 : x(score + (sd ?? 0))
  return (
    <div className={`scorebar ${compact ? 'compact' : ''}`}>
      <div className="track">
        <div className="mid" />
        {score != null && (
          <>
            <div className="band" style={{ left: `${lo}%`, width: `${hi - lo}%`, background: scoreColor(score) }} />
            <div className="pin" style={{ left: `${x(score)}%`, background: scoreColor(score) }} />
          </>
        )}
      </div>
      {!compact && (
        <div className="scorebar-meta">
          <span className="val" style={{ color: scoreColor(score) }}>{fmtScore(score)}</span>
          <span className="sd">±{sd?.toFixed(2) ?? '—'}</span>
          {source && <span className={`chip src-${source.replace('+', '-')}`} title={SOURCE[source]?.note}>{SOURCE[source]?.label ?? source}</span>}
        </div>
      )}
    </div>
  )
}

export function Dossier({ s, dimension, onClose, meta }) {
  const dims = Object.keys(DIMENSIONS)
  const cauc = CAUCUS[s.caucus]
  const tags = []
  if (s.incoming) tags.push(s.newToSenate ? 'INCOMING · FRESHMAN' : 'INCOMING · RETURNING')
  if (s.party && s.party.startsWith('Indep')) tags.push('INDEPENDENT')
  return (
    <aside className="panel dossier">
      <header>
        <div className="kicker">SUBJECT FILE · {s.id}</div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <h2>{s.name}</h2>
      <div className="subline">
        <span className="dot" style={{ background: cauc.color }} />
        {s.state} · {cauc.label} · Class {s.class ?? '—'}
      </div>
      {tags.length > 0 && <div className="tags">{tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>}
      <div className="stats">
        <div><b>{s.seniority ?? '—'}</b><span>SENIORITY RANK</span></div>
        <div><b>{s.years?.toFixed(1) ?? '0.0'}</b><span>YEARS SERVED</span></div>
        <div><b>{s.ideology.d1 == null ? '—' : s.ideology.d1.toFixed(2)}</b><span>DW-NOMINATE</span></div>
      </div>

      <h3>Positions <small>−2 … +2 · band = ±1 SD</small></h3>
      {dims.map((d) => {
        const v = s.scores[d]
        return (
          <div key={d} className={`dimrow ${d === dimension ? 'active' : ''}`}>
            <div className="dimname">
              {DIMENSIONS[d].label}
              <span className="ends">{DIMENSIONS[d].lowTag} ↔ {DIMENSIONS[d].highTag}</span>
            </div>
            <ScoreBar score={v.score} sd={v.sd} source={v.source} />
          </div>
        )
      })}

      <h3>Committees <small>projected, 120th Congress</small></h3>
      {s.committees.length === 0 ? (
        <p className="muted">No seat yet: open seats are filled when committees organize in January.</p>
      ) : (
        <ul className="committees">
          {s.committees
            .slice()
            .sort((a, b) => (a.title ? -1 : 1) - (b.title ? -1 : 1) || a.tier.localeCompare(b.tier))
            .map((c) => (
              <li key={c.id}>
                <span className={`tier t-${c.tier.replace(' ', '')}`}>{c.tier}</span>
                <span className="cname">{c.name.replace('Senate Committee on ', '').replace('Senate Select Committee on ', '')}</span>
                {c.title && <span className="ctitle">{c.title}</span>}
              </li>
            ))}
        </ul>
      )}

      {s.donors && (
        <>
          <h3>PAC money <small>2022–2026 cycles · FEC</small></h3>
          <div className="donors">
            <div><b>{money(s.donors.defense_contractor)}</b><span>DEFENSE CONTRACTOR PACS</span></div>
            <div><b>{money(s.donors.israel_policy)}</b><span>ISRAEL-POLICY PACS</span></div>
          </div>
        </>
      )}
    </aside>
  )
}

export function Briefing({ senators, dimension, meta, onSelect, colorMode }) {
  const scored = senators.filter((s) => s.scores[dimension].score != null)
  const sorted = scored.slice().sort((a, b) => a.scores[dimension].score - b.scores[dimension].score)
  const mean = (c) => {
    const v = scored.filter((s) => s.caucus === c).map((s) => s.scores[dimension].score)
    return v.reduce((a, b) => a + b, 0) / v.length
  }
  const dimMeta = meta.dimensions.find((d) => d.id === dimension)
  const leaders = senators
    .flatMap((s) => s.committees.filter((c) => c.title && ['SSFR', 'SSAS', 'SSAP', 'SLIN'].includes(c.id)).map((c) => ({ s, c })))
    .sort((a, b) => a.c.id.localeCompare(b.c.id) || (a.c.title === 'Chair' ? -1 : 1))
  const sources = scored.reduce((m, s) => ((m[s.scores[dimension].source] = (m[s.scores[dimension].source] ?? 0) + 1), m), {})
  return (
    <aside className="panel briefing">
      <div className="kicker">DIMENSION BRIEF</div>
      <h2>{DIMENSIONS[dimension].label}</h2>
      <p className="ends-desc">
        <span style={{ color: scoreColor(-2) }}>−2 · {dimMeta.low}</span>
        <span style={{ color: scoreColor(2) }}>+2 · {dimMeta.high}</span>
      </p>
      <div className="stats">
        <div><b style={{ color: scoreColor(mean('D')) }}>{fmtScore(mean('D'))}</b><span>DEM CAUCUS MEAN</span></div>
        <div><b style={{ color: scoreColor(mean('R')) }}>{fmtScore(mean('R'))}</b><span>GOP MEAN</span></div>
        <div><b>{dimMeta.calibrated ? dimMeta.rollCalls.length : '—'}</b><span>ROLL CALLS FITTED</span></div>
      </div>
      {dimMeta.calibrated ? (
        <p className="muted small">
          Fitted to {dimMeta.rollCalls.length} Senate roll calls.
          {dimMeta.gammaIdentified && ` President’s-party effect ${dimMeta.gamma > 0 ? '+' : ''}${dimMeta.gamma.toFixed(2)} (latent).`}
          {dimMeta.cv?.within_party_accuracy && ` Held-out within-party accuracy ${(dimMeta.cv.within_party_accuracy * 100).toFixed(0)}%.`}
        </p>
      ) : (
        <p className="muted small">No clean roll calls in the 119th Senate: scores use the starting formula with wide uncertainty.</p>
      )}

      <h3>Poles</h3>
      <div className="poles">
        {[sorted.slice(0, 5), sorted.slice(-5).reverse()].map((list, i) => (
          <ul key={i}>
            {list.map((s) => (
              <li key={s.id} onClick={() => onSelect(s.id)}>
                <span className="dot" style={{ background: CAUCUS[s.caucus].color }} />
                <span className="pname">{s.name}</span>
                <span className="pval" style={{ color: scoreColor(s.scores[dimension].score) }}>{fmtScore(s.scores[dimension].score)}</span>
              </li>
            ))}
          </ul>
        ))}
      </div>

      <h3>Gatekeepers <small>projected chairs and ranking members</small></h3>
      <ul className="gatekeepers">
        {leaders.map(({ s, c }) => (
          <li key={`${c.id}-${s.id}`} onClick={() => onSelect(s.id)}>
            <span className="gk-c">{c.id}</span>
            <span className="gk-t">{c.title.toUpperCase()}</span>
            <span className="dot" style={{ background: CAUCUS[s.caucus].color }} />
            <span className="pname">{s.name}</span>
          </li>
        ))}
      </ul>

      <h3>Evidence base</h3>
      <div className="sourcemix">
        {Object.entries(sources).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
          <span key={k} className={`chip src-${k.replace('+', '-')}`} title={SOURCE[k]?.note}>{SOURCE[k]?.label ?? k} {v}</span>
        ))}
      </div>
    </aside>
  )
}
