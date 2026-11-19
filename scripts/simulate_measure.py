"""Simulate a measure in the projected 120th Senate under each White House.

Usage (PowerShell):
    python scripts\\score_senators.py
    python scripts\\simulate_measure.py israel_arms_disapproval [--runs 20000]
    python scripts\\simulate_measure.py --list

Presets live in senate_sim/simulation.py (PRESETS).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config  # noqa: E402
from senate_sim.policy import calibration, foreign_policy  # noqa: E402
from senate_sim.simulation import PRESETS, required_defectors, simulate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preset", nargs="?")
    parser.add_argument("--runs", type=int, default=10000)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list or not args.preset:
        for k, m in PRESETS.items():
            print(f"{k:<26} {m.name}")
        return 0
    measure = PRESETS[args.preset]

    path = config.PROCESSED_DIR / f"scores_foreign_policy_{config.ROSTER_CONGRESS}.csv"
    if not path.exists():
        print(f"Missing {path}. Run scripts\\score_senators.py first.")
        return 1
    scores = pd.read_csv(path)
    cal = calibration.load(foreign_policy.MODULE.calibration_path)

    print(f"{measure.name}\n{'-' * len(measure.name)}")
    if not cal:
        print("WARNING: no calibration file. Results use placeholder parameters with no\n"
              "President's-party effect; run scripts\\calibrate.py before reading them.")
    if measure.notes:
        print(measure.notes)
    for president in ("R", "D"):
        r = simulate(scores, measure, president, cal, runs=args.runs)
        p = r["parameters"]
        tag = "calibrated" if p["calibrated"] else "uncalibrated defaults"
        if p.get("alpha_mode"):
            tag += f"; cutpoint from {p['alpha_mode']}"
        if p["calibrated"] and not p["gamma_identified"]:
            tag += "; president's-party effect not identified, so D White House is an extrapolation"
        seats = int((scores["caucus"] == president).sum())
        print(f"\n{president} White House ({tag})")
        for name, s in r["stages"].items():
            print(f"  {name:<10} P(pass)={s['p_pass_cumulative']:.3f}  "
                  f"yeas median {s['yeas_median']:.0f} (10-90%: {s['yeas_p10_p90'][0]:.0f}-{s['yeas_p10_p90'][1]:.0f})")
        if "p_senate_override_if_passed" in r:
            print(f"  P(passes both chambers)={r['p_passes_both_chambers']:.3f}  "
                  f"P(Senate override | passed)={r['p_senate_override_if_passed']:.3f}  "
                  f"(needs {required_defectors(seats)} of {seats} {president} senators at full attendance)")
        print(f"  P(enacted)={r['p_enacted']:.4f}")
        print("  most often pivotal: " + ", ".join(
            f"{x['name']} ({x['caucus']}) {x['share']:.0%}" for x in r["pivotal_senators"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
