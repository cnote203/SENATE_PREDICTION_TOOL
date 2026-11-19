"""Fetch sources and write the validated baseline Senate roster.

Usage (PowerShell):
    $env:CONGRESS_API_KEY = "..."      # from api.data.gov
    $env:SENATE_SIM_CONTACT = "you@example.com"
    python scripts\\build_roster.py [--refresh]

Usage (macOS/Linux):
    export CONGRESS_API_KEY=...
    python scripts/build_roster.py [--refresh]

If Congress.gov has not yet published the 120th Congress (it convenes
January 3, 2027), the script projects it from the sitting 119th Congress
plus the hand-maintained seat changes in data/manual/seat_changes_2026.csv.

Writes data/processed/senate_baseline_120.csv and prints a summary.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from senate_sim import config  # noqa: E402
from senate_sim.ingest import congress_gov, voteview  # noqa: E402
from senate_sim.roster import build_baseline, validate_baseline  # noqa: E402
from senate_sim.seat_changes import (  # noqa: E402
    SEAT_CHANGES_PATH,
    apply_seat_changes,
    load_seat_changes,
)


def get_roster(refresh: bool):
    target = config.ROSTER_CONGRESS
    print(f"Fetching Congress.gov roster for the {target}th Congress...")
    try:
        return congress_gov.fetch_senate_roster(congress=target, refresh=refresh), "official"
    except congress_gov.EmptyCongressError as exc:
        print(f"  {exc}")

    current = target - 1
    print(f"Falling back: sitting {current}th Congress plus seat changes in "
          f"{SEAT_CHANGES_PATH.relative_to(PROJECT_ROOT)}")
    sitting = congress_gov.fetch_senate_roster(congress=current, current_only=True, refresh=refresh)
    print(f"  {len(sitting)} sitting senators found.")
    changes = load_seat_changes()
    print(f"  {len(changes)} seat changes listed.")
    return apply_seat_changes(sitting, changes), "projected"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the disk cache")
    parser.add_argument(
        "--out",
        type=Path,
        default=config.PROCESSED_DIR / f"senate_baseline_{config.ROSTER_CONGRESS}.csv",
    )
    args = parser.parse_args()

    roster, source = get_roster(args.refresh)

    print(f"Fetching Voteview member history through the {config.VOTEVIEW_CONGRESS}th Congress...")
    scores = voteview.fetch_member_history(refresh=args.refresh)

    baseline = build_baseline(roster, scores)
    baseline["roster_source"] = source

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Write before validating so a failed split can still be inspected.
    baseline.to_csv(args.out, index=False)
    print(f"Wrote {len(baseline)} senators to {args.out} (roster source: {source})")
    print(baseline["caucus"].value_counts().to_string())

    validate_baseline(baseline)
    print("Validation passed.")

    no_record = baseline[~baseline["has_voting_record"]]
    if not no_record.empty:
        print("No voting record (need another way to set starting positions):")
        print("  " + ", ".join(f"{n} ({s})" for n, s in zip(no_record["name"], no_record["state"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
