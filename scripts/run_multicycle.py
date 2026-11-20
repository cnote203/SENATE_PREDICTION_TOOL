"""Simulate the 120th-122nd Congresses (2027-2032): elections, committees, and measures.

Usage (PowerShell):
    python scripts\\build_roster.py ; python scripts\\calibrate.py   # inputs must exist
    python scripts\\run_multicycle.py                    # 2028 President simulated
    python scripts\\run_multicycle.py --president-2028 D # branch: Democratic White House
    python scripts\\run_multicycle.py --president-2028 R --runs 500

Writes data/processed/multicycle_*.csv.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config, donors, elections, multicycle  # noqa: E402
from senate_sim.ingest import legislators  # noqa: E402
from senate_sim.ingest.http import cached_get  # noqa: E402
from senate_sim.policy import calibration, foreign_policy  # noqa: E402
from senate_sim.simulation import PRESETS  # noqa: E402

P = config.PROCESSED_DIR


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--president-2028", choices=["sim", "D", "R"], default="sim")
    ap.add_argument("--env-2028", type=float, default=None,
                    help="mean 2028 national Democratic margin; default carries half the 2026 environment")
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--inner-runs", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    baseline = pd.read_csv(P / f"senate_baseline_{config.ROSTER_CONGRESS}.csv", dtype={"bioguide_id": str})
    assignments = pd.read_csv(P / f"committee_assignments_{config.ROSTER_CONGRESS}.csv", dtype={"bioguide_id": str})
    people = legislators.index_by_bioguide(legislators.fetch_json("legislators-historical.json"),
                                           legislators.fetch_json("legislators-current.json"))
    birth_years = {b: int(p["bio"]["birthday"][:4]) for b, p in people.items()
                   if p.get("bio", {}).get("birthday")}
    lean_df = elections.state_lean(cached_get(elections.PRES_2024_URL))
    lean = lean_df.set_index("state")["lean"].to_dict()
    cal = calibration.load(foreign_policy.MODULE.calibration_path)

    scenario = multicycle.Scenario(args.president_2028, args.env_2028, args.runs, args.inner_runs, args.seed)
    print(f"Running {args.runs} simulations (2028 President: {args.president_2028})...")
    adj = donors.load_adjustment(P, config.ROSTER_CONGRESS)
    print(f"Donor adjustment for House-only scores: {'on' if adj is not None else 'off'}")
    result = multicycle.run(baseline, birth_years, lean, assignments, foreign_policy.MODULE, cal, PRESETS,
                            scenario, donor_adjustment=adj)
    s = multicycle.summarize(result)

    e = result["environment_2026"]
    print(f"\n2026 environment estimated from {e['seats']} seats: D{e['estimate']:+.1f} "
          f"(+-{e['se']:.1f}); 2028 national mean D{e['env_2028_mean']:+.1f}")
    print("\nSenate and White House by Congress:")
    print(s["congress"].round(2).to_string(index=False))
    print("\nMeasures (averaged over White House outcomes):")
    print(s["measures"].round(3).to_string(index=False))
    print("\nMeasures by White House:")
    print(s["measures_by_white_house"].round(3).to_string(index=False))
    print("\nForeign policy committee leadership (most likely holders):")
    for _, r in s["leadership"].iterrows():
        print(f"  {r['congress']} {r['post']:<14} " + ", ".join(f"{k} {v:.0%}" for k, v in r["top_holders"].items()))

    tag = f"{args.president_2028}"
    for k, df in s.items():
        df.to_csv(P / f"multicycle_{tag}_{k}.csv", index=False)
    result["congress"].to_csv(P / f"multicycle_{tag}_runs.csv", index=False)
    print(f"\nWrote data/processed/multicycle_{tag}_*.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
