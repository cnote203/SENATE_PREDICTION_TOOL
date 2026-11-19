# Senate Policy Simulation

Projects U.S. Senate policy trajectories for the 120th–122nd Congresses (2027–2033).
Foreign policy is the first module; Healthcare, AI/Tech, Energy, and Banking will plug
into the same core engine later.

## Layout

```
src/senate_sim/
  config.py              constants, expected split, API key lookup
  ingest/http.py         GET with retries and disk cache (API keys never cached to disk)
  ingest/legislators.py  congress-legislators: roster, IDs, class, caucus, seniority
  ingest/congress_gov.py Congress.gov v3 roster (optional cross-check)
  ingest/voteview.py     Voteview DW-NOMINATE history, all Congresses, House + Senate
  roster.py              merge, caucus labels, validation gate
  seat_changes.py        projects the 120th roster from the 119th plus seat changes
  committees.py          committee rosters and the 120th Congress projection
  policy/base.py         shared scoring engine: formulas, imputation, overrides, uncertainty
  policy/foreign_policy.py  four foreign policy dimensions
  policy/calibration.py  pooled probit fit of each dimension to roll calls
  ingest/senate_votes.py senate.gov roll-call XML, keyed to Bioguide IDs
  ingest/vote_sources.py Voteview (default) or senate.gov as the source of individual votes
  simulation.py          vote model, procedural gates, Monte Carlo
scripts/build_roster.py  end-to-end baseline build
scripts/score_senators.py  scores the baseline on a policy module
scripts/calibrate.py     fits the dimension formulas to Senate roll calls
scripts/verify_overrides.py  prints each override senator's vote on the cited roll calls
scripts/simulate_measure.py  Monte Carlo for one measure under R and D White Houses
tests/test_roster.py     offline unit tests (no network or keys)
data/raw/                cached API and bulk responses
data/processed/          validated outputs
```

## Setup

Windows (PowerShell):

```powershell
pip install -r requirements.txt
$env:CONGRESS_API_KEY = "..."            # optional: Congress.gov cross-check
$env:SENATE_SIM_CONTACT = "you@example.com"
python -m unittest discover -s tests -v
python scripts\build_roster.py           # add --refresh to ignore the cache
```

macOS/Linux: same, but `export CONGRESS_API_KEY=...` and forward slashes.

## Data sources

| Source | Used for |
|---|---|
| [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) (public domain) | roster, Bioguide/FEC/ICPSR/LIS IDs, Senate class, caucus, service history, current committee membership |
| Voteview | DW-NOMINATE scores |
| Congress.gov API | optional cross-check of the sitting roster |
| `data/manual/seat_changes_2026.csv` | seat changes until the new Congress appears in congress-legislators |

## Outputs (`data/processed/`)

| File | Contents |
|---|---|
| `senate_baseline_120.csv` | one row per senator: caucus, class, seniority, scores, committees, leadership |
| `committee_assignments_120.csv` | one row per committee seat: `member`, `bumped`, or `vacancy` |
| `committee_leadership_120.csv` | projected chair and top minority member, seat split, vacancies |

## Committee projection

Current assignments are projected to the 120th Congress: departing senators leave,
sides follow the new majority, seats are re-split to the chamber ratio (lowest-ranked
members bumped, open seats listed as vacancies), and the top remaining member on each
side takes the chair or ranking post, one post per senator, Super A committees first.
These are projections; conferences decide in January. Tiers, ratios and the one-post
limit are in `config.py` and marked AUDIT.

## Before January 3, 2027: projected roster

`build_roster.py` takes the sitting senators from congress-legislators and applies
`data/manual/seat_changes_2026.csv`, one row per seat that gets a new senator. A row
is skipped automatically once the swap shows up in the source data (special-election
winners sworn in early, and everyone after January 3):

| column | meaning |
|---|---|
| state | postal code, e.g. `MI` |
| outgoing_bioguide | Bioguide ID of the senator leaving (find it in the 119th output) |
| incoming_name | the incoming senator |
| incoming_party | `Democratic`, `Republican`, or `Independent` |
| incoming_bioguide | their Bioguide ID if they have one (ex-House members do), else blank |
| caucus_with_d | `yes` for an independent who caucuses with Democrats |

Incoming senators without a Bioguide ID get a placeholder like `NEW-MI-1`. The output
CSV is written before validation, so a wrong split can be inspected.

## Service and record columns

| column | meaning |
|---|---|
| incoming | taking a seat in the 120th Congress |
| new_to_senate | incoming with no prior Senate service (a returning ex-senator is `False`) |
| has_voting_record | has any DW-NOMINATE score, House or Senate |
| score_chamber / score_congress | where the latest score came from; House-derived scores deserve wider uncertainty |
| senate_congresses_served / first_senate_congress | prior Senate service, for seniority |

## Notes

- **Caucus, not party.** Angus King (I-ME) and Bernie Sanders (I-VT) caucus with the
  Democrats, so majority math uses the `caucus` column. The `api_party` and `vv_party`
  columns keep the original labels.
- **Validation gate.** `validate_baseline` fails the build unless the roster has 100
  senators and the 56 D / 44 R split from AP's results. Change `EXPECTED_SPLIT` in
  `config.py` if the count changes.
- **Congress.gov does not list committee rosters in the member endpoint.** Committee
  assignments (SFRC, SASC, Appropriations, Intelligence, and the chairs and ranking
  members) need a separate source, such as the Senate.gov committee membership XML
  feeds. That is the next ingestion step.
- **Timing.** Before January 3, 2027, Congress.gov and Voteview may not yet have
  complete 120th Congress data. Re-run with `--refresh` after the Congress convenes.
- **OpenFEC** (PAC and industry contributions) is not wired in yet. It comes after the
  roster and committee data are validated.

## Policy scores

```powershell
python scripts\score_senators.py            # foreign policy by default
```

Writes `data/processed/scores_foreign_policy_120.csv`: for each senator and dimension,
a score from -2 to +2, a standard deviation, and its source.

| Source | How the score is set | SD |
|---|---|---|
| `formula` | DW-NOMINATE point through the dimension's formula | 0.25 (Senate score), 0.45 (House score) |
| `imputed` | no record: caucus median, pulled 35% toward centre if the state's other senator is from the other caucus | 0.80 |
| `override` | `data/manual/overrides_<module>.csv`, one row per senator and dimension with evidence | from the file |

Foreign policy dimensions:

| Dimension | -2 | +2 |
|---|---|---|
| nato_interventionism | restraint: limits war powers and commitments, cuts aid | backs alliance commitments, military aid, use of force |
| defense_budget | cuts or flat budgets | increases above the President's request |
| arms_sales_oversight | defers to the executive | supports disapproval resolutions and conditions |
| china_decoupling | engagement and trade | tariffs, export controls, investment screening |

The seeded overrides are marked `verified = no`: check each against the roll call and
set it to `yes`. Formula coefficients and uncertainty settings are marked AUDIT.

A new policy area is one file in `policy/` defining a `MODULE` with its dimensions,
plus an overrides CSV; run it with `--module <name>`.

## Calibration

```powershell
python scripts\calibrate.py          # reads votes from Voteview; add --source senate for senate.gov
git add data\calibration
git commit -m "Calibrate foreign policy dimensions"
```

`data/manual/calibration_votes.csv` lists the roll calls used for each dimension, which
side is the +2 side, a family (near-replicate votes share one), and the President's party
at the time. The fit is a pooled probit per dimension:

P(+2 side) = Phi(item cutpoint + b1*d1 + b2*d1^2 + b3*d2 + gamma*[in President's party] + senator deviation)

- Items whose losing side is under 2.5% are dropped (W-NOMINATE's default).
- Families are down-weighted by 1/sqrt(size), so the Iran war powers series can't dominate.
- Present and Not Voting are treated as missing.
- gamma is only estimated when a dimension has votes from both a Democratic and a
  Republican White House (the 2024 Biden-era Ukraine and Israel votes provide this for
  `nato_interventionism` and `arms_sales_oversight`).
- `china_decoupling` is not calibrated. There are no clean China roll calls in the 119th
  Senate, and tariff-emergency votes measure deference to the President. It keeps its
  prior formula with an SD of at least 0.6.

The mapping and each senator's deviation are estimated together (alternating rounds), so
a few idiosyncratic senators are explained by their own deviation instead of bending the
curve for everyone. Thin dimensions (fewer than 8 items or a single family, such as the
FY26 NDAA votes for `defense_budget`) hold the curve-shape terms to a tighter prior.

**Reading calibrated scores.** When the President's-party effect (gamma) is estimated, a
score is the senator's position *outside* the President's party; the simulation adds gamma
for members of the President's party. On `nato_interventionism` gamma is large and
positive (senators rally behind their own President's use of force and aid requests), so
mainstream Democrats score toward restraint in 2025-26 terms while still voting hawkish
under a Democratic White House. On `arms_sales_oversight` gamma is negative (co-partisans
defend the President's sales).

Outputs: `data/calibration/foreign_policy.json` (used automatically by scoring and
simulation) and `foreign_policy_deviations.csv` (how far each senator sits from the fit).
The script lists senators who sit clearly off the fit and have no override yet.

Votes come from Voteview's bulk files by default. senate.gov is authoritative and same-day
but refuses automated requests from many networks (HTTP 403); `--source senate` tries it.
Roll calls are always cited by their senate.gov number within a session; Voteview's
`clerk_rollnumber` maps them.

Each override cites roll calls (`congress-session-roll`). To check them:

```powershell
python scripts\verify_overrides.py
```

## Simulating a measure

```powershell
python scripts\simulate_measure.py --list
python scripts\simulate_measure.py israel_arms_disapproval --runs 20000
```

Each run draws every senator's position error once (shared across measures on that
dimension), a shock per caucus per measure, the measure's cutpoint from its family's fitted
votes, and attendance (97%). Gates: simple majority (ties go the White House's way via the
Vice President), cloture (60), two-thirds of those voting (treaties, overrides). Disapproval
and war powers resolutions go discharge, then passage, then veto (97% if the President
opposes), then a two-thirds override in both chambers. The House is an input probability,
not modelled member by member. Output: pass probabilities by stage, yea-count ranges,
P(enacted), and the senators most often pivotal, under an R and a D White House.

## Status

- [x] Project layout, config, HTTP cache
- [x] Voteview parser (tested offline)
- [x] Congress.gov roster parser (tested offline; field names need one live check)
- [x] Caucus labels and 100-seat validation gate
- [x] Projected roster from seat changes before Jan 3
- [x] House and prior-Senate scores for incoming senators; service history
- [x] congress-legislators as primary source; Congress.gov as cross-check
- [x] Seniority rank, Senate class, FEC IDs
- [x] Committee rosters and projected leadership for the 120th Congress
- [ ] Co-sponsorship data
- [ ] OpenFEC contributions
- [x] Shared scoring engine; foreign policy module with seeded overrides
- [x] Calibration pipeline (senate.gov roll calls, pooled probit, deviations)
- [x] Overrides revised against the roll-call record, with citations
- [x] Single-measure vote model, procedural gates, Monte Carlo
- [ ] Run calibration and commit `data/calibration/`
- [ ] Add 2019-2020 Saudi/Gulf votes so Republican arms-sale positions are identified
- [ ] Electoral-vulnerability and leadership terms in the vote model
- [ ] Multi-cycle simulation (2028 and 2030 seat turnover, seniority, White House scenarios)
