import { CAUCUS, SOURCE, fmtScore, money, scoreColor, tag } from '../util.js'

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

export function Dossier({ s, sector, dimension, onClose, meta, onSector }) {
  const cauc = CAUCUS[s.caucus]
  const tags = []
  if (s.incoming) tags.push(s.newToSenate ? 'Incoming, new to the Senate' : 'Incoming, returning')
  if (s.party && s.party.startsWith('Indep')) tags.push('Independent')
  const mod = meta.modules.find((m) => m.id === sector)
  const others = meta.modules.filter((m) => m.id !== sector)
  return (
    <aside className="panel dossier">
      <header>
        <div className="kicker">{s.id}</div>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
      </header>
      <h2>{s.name}</h2>
      <div className="subline">
        <span className="dot" style={{ background: cauc.color }} />
        {s.state} · {cauc.label} · Class {s.class ?? '—'}
      </div>
      {tags.length > 0 && <div className="tags">{tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>}
      <div className="stats">
        <div><b>{s.seniority ?? '—'}</b><span>Seniority rank</span></div>
        <div><b>{s.years?.toFixed(1) ?? '0.0'}</b><span>Years served</span></div>
        <div><b>{s.ideology.d1 == null ? '—' : s.ideology.d1.toFixed(2)}</b><span>DW-NOMINATE</span></div>
      </div>

      <h3>{mod.label} <small>−2 … +2 · band = ±1 SD</small></h3>
      {mod.dimensions.map((d) => {
        const v = s.scores[sector]?.[d.id]
        if (!v) return null
        return (
          <div key={d.id} className={`dimrow ${d.id === dimension ? 'active' : ''}`}>
            <div className="dimname">
              {d.label}
              <span className="ends">{tag(d.lowTag)} to {tag(d.highTag).toLowerCase()}</span>
            </div>
            <ScoreBar score={v.score} sd={v.sd} source={v.source} />
          </div>
        )
      })}

      <h3>Other sectors <small>click to switch</small></h3>
      <div className="profile-grid">
        {others.map((m) => (
          <div key={m.id} className="profile-sector" onClick={() => onSector(m.id)}>
            <div className="ps-name">{m.label}</div>
            {m.dimensions.map((d) => {
              const v = s.scores[m.id]?.[d.id]
              return (
                <div key={d.id} className="ps-row" title={`${d.label}: ${fmtScore(v?.score)} (${SOURCE[v?.source]?.label ?? '—'})`}>
                  <span className="ps-dim">{d.short}</span>
                  <ScoreBar score={v?.score} sd={v?.sd} compact />
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <h3>Committees <small>projected, 120th Congress</small></h3>
      {s.committees.length === 0 ? (
        <p className="muted">No seat yet: open seats are filled when committees organize in January.</p>
      ) : (
        <ul className="committees">
          {s.committees
            .slice()
            .sort((a, b) => (a.title ? -1 : 1) - (b.title ? -1 : 1) || a.tier.localeCompare(b.tier))
            .map((c) => (
              <li key={c.id} className={mod.committees.some((x) => x.id === c.id) ? 'relevant' : ''}>
                <span className={`tier t-${c.tier.replace(' ', '')}`}>{c.tier}</span>
                <span className="cname">{c.name.replace('Senate Committee on ', '').replace('Senate Select Committee on ', '').replace('Special Committee on ', '')}</span>
                {c.title && <span className="ctitle">{c.title}</span>}
              </li>
            ))}
        </ul>
      )}

      {s.donors && (
        <>
          <h3>PAC money <small>2022–2026 cycles · FEC</small></h3>
          <div className="donors">
            <div><b>{money(s.donors.defense_contractor)}</b><span>Defense contractor PACs</span></div>
            <div><b>{money(s.donors.israel_policy)}</b><span>Israel-policy PACs</span></div>
          </div>
        </>
      )}
    </aside>
  )
}

export function Briefing({ senators, sector, dimension, meta, onSelect }) {
  const mod = meta.modules.find((m) => m.id === sector)
  const dimMeta = mod.dimensions.find((d) => d.id === dimension)
  const val = (s) => s.scores[sector]?.[dimension]
  const scored = senators.filter((s) => val(s)?.score != null)
  const sorted = scored.slice().sort((a, b) => val(a).score - val(b).score)
  const mean = (c) => {
    const v = scored.filter((s) => s.caucus === c).map((s) => val(s).score)
    return v.reduce((a, b) => a + b, 0) / v.length
  }
  const committeeIds = mod.committees.map((c) => c.id)
  const leaders = senators
    .flatMap((s) => s.committees.filter((c) => c.title && committeeIds.includes(c.id)).map((c) => ({ s, c })))
    .sort((a, b) => committeeIds.indexOf(a.c.id) - committeeIds.indexOf(b.c.id) || (a.c.title === 'Chair' ? -1 : 1))
  const sources = scored.reduce((m, s) => ((m[val(s).source] = (m[val(s).source] ?? 0) + 1), m), {})
  return (
    <aside className="panel briefing">
      <div className="kicker">{mod.label}</div>
      <h2>{dimMeta.label}</h2>
      <p className="ends-desc">
        <span style={{ color: scoreColor(-2) }}>−2 · {dimMeta.low}</span>
        <span style={{ color: scoreColor(2) }}>+2 · {dimMeta.high}</span>
      </p>
      <div className="stats">
        <div><b style={{ color: scoreColor(mean('D')) }}>{fmtScore(mean('D'))}</b><span>Democratic average</span></div>
        <div><b style={{ color: scoreColor(mean('R')) }}>{fmtScore(mean('R'))}</b><span>Republican average</span></div>
        <div><b>{dimMeta.calibrated ? dimMeta.rollCalls.length : '—'}</b><span>Roll calls fitted</span></div>
      </div>
      {dimMeta.calibrated ? (
        <p className="muted small">
          Fitted to {dimMeta.rollCalls.length} Senate roll calls.
          {dimMeta.gammaIdentified && ` President’s-party effect ${dimMeta.gamma > 0 ? '+' : ''}${dimMeta.gamma.toFixed(2)} (latent).`}
          {dimMeta.cv?.within_party_accuracy && ` Held-out within-party accuracy ${(dimMeta.cv.within_party_accuracy * 100).toFixed(0)}%.`}
        </p>
      ) : dimMeta.plannedRollCalls > 0 ? (
        <div className="warn">Not yet fitted: {dimMeta.plannedRollCalls} roll calls are queued. Scores use the starting formula until calibrate.py runs.</div>
      ) : (
        <div className="warn">Illustrative only: no usable roll calls in the 119th Senate. Scores use the starting formula with wide uncertainty.</div>
      )}

      <h3>Poles</h3>
      <div className="poles">
        {[sorted.slice(0, 5), sorted.slice(-5).reverse()].map((list, i) => (
          <ul key={i}>
            {list.map((s) => (
              <li key={s.id} onClick={() => onSelect(s.id)}>
                <span className="dot" style={{ background: CAUCUS[s.caucus].color }} />
                <span className="pname">{s.name}</span>
                <span className="pval" style={{ color: scoreColor(val(s).score) }}>{fmtScore(val(s).score)}</span>
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
            <span className="gk-t">{c.title}</span>
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
