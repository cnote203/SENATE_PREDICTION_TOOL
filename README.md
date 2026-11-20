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
  elections.py           state lean, 2026 environment estimate, Senate and presidential draws
  multicycle.py          120th-122nd Congress simulation loop
scripts/build_roster.py  end-to-end baseline build
scripts/score_senators.py  scores the baseline on a policy module
scripts/calibrate.py     fits the dimension formulas to Senate roll calls
scripts/verify_overrides.py  prints each override senator's vote on the cited roll calls
scripts/simulate_measure.py  Monte Carlo for one measure under R and D White Houses
scripts/fetch_donors.py  OpenFEC PAC contributions per senator, and a test of whether they explain votes
scripts/run_multicycle.py  2027-2032 simulation: elections, committees, measures per Congress
scripts/export_web.py    exports results as JSON for the web app
scripts/fetch_hearings.py  Senate committee hearing schedule for the HEARINGS mode
web/                     Senate Situation Board (React + Vite)
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
FY26 NDAA votes for `defense_budget`) hold the curve-shape terms to a tighter prior, and
DW-NOMINATE dim2 to a tighter one still (it is noisy in recent Congresses).

`calibrate.py` also checks every senator's final score (override or fitted) against their
votes and lists anyone whose observed share of +2-side votes differs from the predicted
share by 0.4 or more over at least 3 votes (`<module>_consistency.csv`).

**Senators' own votes count.** For every senator who voted on a dimension's roll calls,
the score is the ideology mapping plus that senator's own estimated deviation (shrunk
toward the mapping, with its standard error as the score's SD; source `votes`). The
mapping alone is used only for senators without such votes (House-only records, source
`fitted`) and new senators (`imputed`). The score scale is set by the spread of these
full positions, so overrides keep their intended strength even where ideology explains
little (defense).

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

Issues whose support is moving use `alpha_mode="latest"`: the cutpoint starts at the
family's most recent vote and reverts toward the family average with an 18-month
half-life (mean-reverting drift, so uncertainty levels off instead of growing without
limit), with volatility estimated from the family's own vote-to-vote changes (Israel arms sales: 15 to
40 yeas in a year). Stable issues draw from the whole family.

Each run draws every senator's position error once (shared across measures on that
dimension), a shock per caucus per measure, the measure's cutpoint from its family's fitted
votes, and attendance (97%). Gates: simple majority (ties go the White House's way via the
Vice President), cloture (60), two-thirds of those voting (treaties, overrides). Disapproval
and war powers resolutions go discharge, then passage, then veto (97% if the President
opposes), then a two-thirds override in both chambers. The House is an input probability,
not modelled member by member. Output: pass probabilities by stage, yea-count ranges,
P(enacted), and the senators most often pivotal, under an R and a D White House.

## Donor data (OpenFEC)

```powershell
python scripts\fetch_donors.py --resolve   # find the PACs' FEC committee IDs
# review data\manual\donor_pacs.csv: set include to yes/no
python scripts\fetch_donors.py             # pull contributions, test against votes
```

FEC data has no industry codes (and the OpenSecrets API was shut down in 2025), so
categories come from PAC name patterns in `data/manual/donor_categories.csv`: defense
contractors and Israel-policy PACs. Contributions are totalled per senator over the
2022, 2024 and 2026 cycles, across all of each senator's FEC candidate IDs (House IDs
included). Only direct PAC-to-campaign money is counted; super PAC spending and
conduit-bundled individual contributions are not.

The script then regresses each senator's calibrated deviation on log PAC dollars,
within caucus, for defense money against `defense_budget` and `nato_interventionism`
and Israel-policy money against `arms_sales_oversight`. A significant slope in the
expected direction means donor data carries information the ideology mapping misses;
only then is it worth adding to the vote model. It is a correlation: PACs give to
senators who already agree with them.

The same api.data.gov key works for Congress.gov and OpenFEC.

**Donor adjustment.** Where a donor effect passes the test, `score_senators.py` and
`run_multicycle.py` use it to adjust scores that come only from a House record (source
`fitted`, becoming `fitted+donors`): shift = slope x (log PAC dollars - mean of other
House-only senators in the same caucus), capped at +-0.75. Senators with their own Senate
votes are not adjusted (their votes already reflect it), and neither are new senators
with no record (challenger PAC receipts mostly reflect incumbency and corporate-PAC
pledges). SDs are left unchanged. Delete `data/processed/donor_effects.csv` to turn it off.

## Multi-cycle simulation (2027-2032)

```powershell
python scripts\run_multicycle.py                       # 2028 President simulated
python scripts\run_multicycle.py --president-2028 D    # Democratic White House branch
python scripts\run_multicycle.py --president-2028 R    # Republican White House branch
python scripts\run_multicycle.py --env-2028 0          # neutral 2028 environment
```

Each run carries the 120th Congress forward through the 2028 (Class 3) and 2030
(Class 1) elections:

- **State lean:** 2024 presidential two-party margin relative to the nation (county
  results from tonmcg/US_County_Level_Election_Results_08-24, aggregated to states).
- **2026 environment:** estimated by maximum likelihood from which party won each seat
  up in 2026 (your seat-change file). The 2028 environment starts at half of it
  (`ENV_RETENTION`) unless `--env-2028` is given; 2030 penalises the President's party.
- **Races:** lean + environment + incumbency (3 points) + race noise (6 points).
  Incumbents may retire first, with a probability that rises with age.
- **President 2028:** state margins = lean + national + state noise; Electoral College
  winner-take-all. A fixed branch is drawn by rejection sampling, so the environment
  stays consistent with the result.
- **Control:** 51 seats, or 50 plus the Vice President.
- **New senators:** scored with the no-record rule; overrides follow the senators who stay.
- **Committees:** re-projected each Congress from the previous one; vacancies filled
  with unassigned senators (at most 3 committees, 1 Super A each).
- **Measures:** every preset simulated in every Congress under that run's White House.

Outputs `data/processed/multicycle_<branch>_*.csv`: Senate and White House odds by
Congress, measure pass and enactment probabilities (overall and by White House), and
the most likely chair and ranking member of each foreign policy committee.

All election constants are in `elections.py`, marked AUDIT.

## Web app: Senate Situation Board

An interactive front end in `web/` (React + Vite), deployed to GitHub Pages.

- **Chamber:** the 100 seats as a hemicycle, ordered left to right by score on the chosen
  dimension. Colour by score, caucus, uncertainty, or evidence source. Click a seat for
  the senator's file: four scores with uncertainty bands and sources, projected
  committees and titles, and PAC money.
- **Roll call:** pick a measure and a White House; seats show each senator's Yea
  probability, then "Call the roll" draws one vote and reveals it alphabetically, with
  the model's pass odds, Yea-count distribution, and most often pivotal senators.
- **2027-2032:** the multi-cycle projection for a Democratic or Republican 2028 winner:
  seats, control, measure odds and likely chairs per Congress.

Refresh the data after rerunning the pipeline, then commit `web/public/data`:

```powershell
python scripts\export_web.py
cd web
npm install
npm run dev        # local preview at http://localhost:5173/SENATE_PREDICTION_TOOL/
```

Deploying: in the GitHub repository, Settings -> Pages -> Source: **GitHub Actions**.
Every push to `main` that touches `web/` then rebuilds and publishes the site at
`https://cnote203.github.io/SENATE_PREDICTION_TOOL/`.

## Hearings: schedule and live viewing

The board's HEARINGS mode lists Senate committee hearings from two weeks back to
four weeks ahead. Each hearing is tagged with every sector whose committees hold
it, shows the projected members on the dais (coloured on that sector's scores),
witnesses and agenda items, and marks hearings LIVE from 10 minutes before the
gavel until 3 hours after.

```
$env:CONGRESS_API_KEY = "<your key>"
python scripts\fetch_hearings.py        # writes web/public/data/hearings.json
```

To refresh it automatically, add the key as a repository secret named
`CONGRESS_API_KEY` (Settings > Secrets and variables > Actions). The Pages
workflow then fetches the schedule before every build and runs hourly on
weekdays. Without the secret the site uses the last committed hearings.json.

Watching: Senate committees stream their own hearings, and C-SPAN covers many.
C-SPAN permits non-commercial use of its federal-event coverage with
attribution, but its cable-channel streams require pay-TV sign-in, so the board
links out to the committee webcast, C-SPAN and Congress.gov rather than pulling
streams. For an in-app player, put the hearing's event ID and an embeddable URL
(the `src` of C-SPAN's embed code, a YouTube link, or a senate.gov player) in
`data/manual/hearing_streams.csv`. Other hosts are shown as links only. Keep
the site non-commercial if you embed C-SPAN video.

## Sectors

| Sector | Module | Dimensions | Calibrated from roll calls |
|---|---|---|---|
| Foreign policy | `foreign_policy` | interventionism, defense budget, arms-sale oversight, China decoupling | 3 of 4 (35 votes) |
| Healthcare | `healthcare` | coverage expansion, drug price controls, public health funding | coverage: S.3385, S.3386 (Dec 2025 ACA credit votes), H.R.1 |
| Energy | `energy` | clean energy, fossil production, permitting reform | clean energy: H.J.Res. 35 (methane fee), H.J.Res. 87/88/89 (California waivers) |
| Banking | `banking` | consumer finance rules, crypto support, bank regulation | consumer finance: S.J.Res. 18, 28 (CFPB CRAs); crypto: S.1582 (GENIUS), H.R. 3633 (CLARITY) |
| AI & tech | `tech` | AI regulation, platform accountability, tech antitrust | none: the one AI roll call was 99-1; sponsorship-based overrides only |

Each module (`src/senate_sim/policy/<module>.py`) defines its dimensions with labelled
endpoints and a starting formula, its preset measures (with the White House's position
under each party), its gatekeeping committees, an overrides CSV and a calibration file.

New-sector roll calls are listed in `calibration_votes.csv` by **bill and question**
(e.g. `S1582`, `Cloture|Passage`) instead of roll number; `calibrate.py` finds the
matching Senate votes in Voteview and refuses any whose bill doesn't match.

```powershell
python scripts\calibrate.py --module all
python scripts\score_senators.py --module all
python scripts\simulate_measure.py --list
python scripts\simulate_measure.py aca_credit_extension --module healthcare
python scripts\run_multicycle.py --president-2028 D     # all sectors, same elections
python scripts\export_web.py
```

Dimensions without usable roll calls keep their starting formula with wide uncertainty,
and measures on them are labelled ILLUSTRATIVE in the web app.

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
- [x] OpenFEC PAC contributions and donor-effect test
- [ ] Electoral-vulnerability and leadership terms in the vote model
- [x] Multi-cycle simulation (2028 and 2030 elections, committees, White House branches)
- [x] Healthcare, energy, banking and AI/tech sectors on the same engine
- [ ] Run sector calibration on Voteview and commit data/calibration
- [ ] Calibrate election constants against past Senate results
- [ ] Electoral vulnerability in the vote model (senators up next cycle)
