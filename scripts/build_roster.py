"""Fetch sources and write the validated baseline Senate roster.

Usage:
    export CONGRESS_API_KEY=...   # from api.data.gov
    export SENATE_SIM_CONTACT=you@example.com
    python scripts/build_roster.py [--refresh]

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the disk cache")
    parser.add_argument(
        "--out",
        type=Path,
        default=config.PROCESSED_DIR / f"senate_baseline_{config.ROSTER_CONGRESS}.csv",
    )
    args = parser.parse_args()

    print(f"Fetching Congress.gov roster for the {config.ROSTER_CONGRESS}th Congress...")
    roster = congress_gov.fetch_senate_roster(refresh=args.refresh)

    print(f"Fetching Voteview scores for the {config.VOTEVIEW_CONGRESS}th Congress...")
    scores = voteview.fetch_senate_members(refresh=args.refresh)

    baseline = build_baseline(roster, scores)
    validate_baseline(baseline)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    baseline.to_csv(args.out, index=False)

    print(f"Wrote {len(baseline)} senators to {args.out}")
    print(baseline["caucus"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
