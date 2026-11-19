"""Build the validated 120th Congress Senate baseline and committee projection.

Usage (PowerShell):
    python scripts\\build_roster.py [--refresh]

Optional cross-check against Congress.gov (needs a free api.data.gov key):
    $env:CONGRESS_API_KEY = "..."

Sources:
  roster, IDs, class, caucus, service   unitedstates/congress-legislators
  seat changes before Jan 3             data/manual/seat_changes_2026.csv
  ideology scores                       Voteview DW-NOMINATE
  committees                            congress-legislators (current), projected

Outputs in data/processed/:
  senate_baseline_120.csv               one row per senator
  committee_assignments_120.csv         one row per committee seat (members, bumped, vacancies)
  committee_leadership_120.csv          projected chair and top minority member per committee
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import committees, config  # noqa: E402
from senate_sim.ingest import congress_gov, legislators, voteview  # noqa: E402
from senate_sim.roster import build_baseline, validate_baseline  # noqa: E402
from senate_sim.seat_changes import SEAT_CHANGES_PATH, apply_seat_changes, load_seat_changes  # noqa: E402

OUT = config.PROCESSED_DIR
N = config.ROSTER_CONGRESS


def cross_check_congress_gov(sitting: pd.DataFrame, refresh: bool) -> None:
    if not os.environ.get(config.CONGRESS_API_KEY_ENV):
        print("  (Congress.gov cross-check skipped: no API key set)")
        return
    try:
        cg = congress_gov.fetch_senate_roster(congress=N - 1, current_only=True, refresh=refresh)
    except Exception as exc:  # the cross-check must never block the build
        print(f"  Congress.gov cross-check failed: {exc}")
        return
    ours, theirs = set(sitting["bioguide_id"]), set(cg["bioguide_id"])
    if ours == theirs:
        print(f"  Congress.gov agrees on all {len(ours)} sitting senators.")
    else:
        print(f"  Congress.gov differs. Only in congress-legislators: {sorted(ours - theirs)}; "
              f"only in Congress.gov: {sorted(theirs - ours)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the disk cache")
    args = parser.parse_args()

    print("Loading congress-legislators...")
    current = legislators.fetch_json("legislators-current.json", refresh=args.refresh)
    historical = legislators.fetch_json("legislators-historical.json", refresh=args.refresh)
    people = legislators.index_by_bioguide(historical, current)
    sitting = legislators.senators_from_current(current)
    print(f"  {len(sitting)} sitting senators.")
    cross_check_congress_gov(sitting, args.refresh)

    changes = load_seat_changes()
    roster = apply_seat_changes(sitting, changes)
    source = "projected" if roster["incoming"].any() else "current"
    print(f"  {len(changes)} seat changes in {SEAT_CHANGES_PATH.relative_to(PROJECT_ROOT)}.")
    roster = legislators.add_service(roster, people)

    print(f"Loading Voteview history through the {config.VOTEVIEW_CONGRESS}th Congress...")
    scores = voteview.fetch_member_history(refresh=args.refresh)
    baseline = build_baseline(roster, scores)
    baseline["roster_source"] = source

    print("Projecting committees...")
    membership = legislators.fetch_json("committee-membership-current.json", refresh=args.refresh)
    committee_list = legislators.fetch_json("committees-current.json", refresh=args.refresh)
    current_seats = committees.parse_membership(membership, committee_list)
    assignments, leadership = committees.project(current_seats, baseline)
    summary = committees.senator_summary(assignments)
    baseline = baseline.merge(summary, on="bioguide_id", how="left")
    baseline["committees"] = baseline["committees"].fillna("")
    baseline["leadership"] = baseline["leadership"].fillna("")
    baseline["n_super_a"] = baseline["n_super_a"].fillna(0).astype(int)
    for cid in config.FOREIGN_POLICY_COMMITTEES:
        baseline[f"on_{cid}"] = baseline[f"on_{cid}"].astype("boolean").fillna(False).astype(bool)

    OUT.mkdir(parents=True, exist_ok=True)
    baseline.to_csv(OUT / f"senate_baseline_{N}.csv", index=False)
    assignments.to_csv(OUT / f"committee_assignments_{N}.csv", index=False)
    leadership.to_csv(OUT / f"committee_leadership_{N}.csv", index=False)
    print(f"Wrote {len(baseline)} senators, {len(assignments)} committee seats, "
          f"{len(leadership)} committees to {OUT} (roster source: {source})")
    print(baseline["caucus"].value_counts().to_string())

    validate_baseline(baseline)
    print("Validation passed.")

    no_record = baseline[~baseline["has_voting_record"]]
    if not no_record.empty:
        print(f"No voting record ({len(no_record)}): "
              + ", ".join(f"{n} ({s})" for n, s in zip(no_record["name"], no_record["state"])))

    fp = leadership[leadership["committee_id"].isin(config.FOREIGN_POLICY_COMMITTEES)]
    print("\nProjected foreign policy committee leadership:")
    for _, r in fp.iterrows():
        print(f"  {r['committee_name']}: {r['chair_title']} {r['chair_name']}; "
              f"{r['ranking_title']} {r['ranking_name']}; "
              f"seats {r['majority_seats']}-{r['minority_seats']}, "
              f"open maj {r['majority_vacancies']}, open min {r['minority_vacancies']}, "
              f"bumped {r['majority_bumped'] + r['minority_bumped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
