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
scripts/build_roster.py  end-to-end baseline build
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
- [ ] Scoring engine and Monte Carlo cycles
