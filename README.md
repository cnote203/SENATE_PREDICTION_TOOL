# Senate Policy Simulation

Projects U.S. Senate policy trajectories for the 120th–122nd Congresses (2027–2033).
Foreign policy is the first module; Healthcare, AI/Tech, Energy, and Banking will plug
into the same core engine later.

## Layout

```
src/senate_sim/
  config.py              constants, expected split, API key lookup
  ingest/http.py         GET with retries and disk cache (API keys never cached to disk)
  ingest/congress_gov.py Congress.gov v3 member roster for a Congress
  ingest/voteview.py     Voteview DW-NOMINATE scores (bulk CSV)
  roster.py              merge, caucus labels, validation gate
scripts/build_roster.py  end-to-end baseline build
tests/test_roster.py     offline unit tests (no network or keys)
data/raw/                cached API and bulk responses
data/processed/          validated outputs
```

## Setup

```bash
pip install pandas requests
export CONGRESS_API_KEY=...          # api.data.gov key
export SENATE_SIM_CONTACT=you@example.com
python -m unittest discover -s tests -v
python scripts/build_roster.py       # add --refresh to ignore the cache
```

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
- [ ] Committee rosters and leadership roles
- [ ] Co-sponsorship data
- [ ] OpenFEC contributions
- [ ] Scoring engine and Monte Carlo cycles
