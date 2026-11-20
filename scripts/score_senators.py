"""Score every senator in the baseline on a policy module's dimensions.

Usage (PowerShell):
    python scripts\\build_roster.py          # first, if the baseline is stale
    python scripts\\score_senators.py [--module foreign_policy]

Writes data/processed/scores_<module>_120.csv.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config, donors  # noqa: E402
from senate_sim.policy import calibration  # noqa: E402
from senate_sim.policy.base import score  # noqa: E402

N = config.ROSTER_CONGRESS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="foreign_policy")
    args = parser.parse_args()

    module = importlib.import_module(f"senate_sim.policy.{args.module}").MODULE
    baseline_path = config.PROCESSED_DIR / f"senate_baseline_{N}.csv"
    if not baseline_path.exists():
        print(f"Missing {baseline_path}. Run scripts\\build_roster.py first.")
        return 1
    baseline = pd.read_csv(baseline_path, dtype={"bioguide_id": str})

    cal = calibration.load(module.calibration_path) if module.calibration_path else None
    fitted = sorted(cal) if cal else []
    print(f"Calibrated dimensions: {', '.join(fitted) if fitted else 'none (using prior formulas)'}")
    adj = donors.load_adjustment(config.PROCESSED_DIR, N)
    if adj is not None:
        used = adj[1][adj[1]["supports_hypothesis"].astype(bool)]
        print("Donor adjustment for House-only scores: "
              + (", ".join(f"{r.category} -> {r.dimension}" for r in used.itertuples()) or "no supported effects"))
    else:
        print("Donor adjustment: off (run scripts\\fetch_donors.py to enable)")
    scores = score(baseline, module, cal, donor_adjustment=adj)
    out = config.PROCESSED_DIR / f"scores_{module.name}_{N}.csv"
    scores.to_csv(out, index=False)

    dims = module.dimension_names
    print(f"Scored {len(scores)} senators on {len(dims)} {module.name} dimensions -> {out}")
    print("\nCaucus means:")
    print(scores.groupby("caucus")[dims].mean().round(2).to_string())
    adj_cols = [c for c in scores.columns if c.endswith("_donor_adj")]
    for c in adj_cols:
        moved = scores[scores[c].fillna(0).abs() > 0.005].sort_values(c)
        if not moved.empty:
            print(f"\n{c[:-10]} donor adjustments ({len(moved)} senators): "
                  + ", ".join(f"{n} {v:+.2f}" for n, v in zip(moved["name"], moved[c])))
    sources = pd.concat([scores[f"{d}_source"] for d in dims]).value_counts()
    print("\nScore sources across all dimensions:", sources.to_dict())
    for d in dims:
        top = scores.nlargest(3, d)
        low = scores.nsmallest(3, d)
        print(f"\n{d}\n  highest: " + ", ".join(f"{n} {v:+.2f}" for n, v in zip(top["name"], top[d]))
              + "\n  lowest:  " + ", ".join(f"{n} {v:+.2f}" for n, v in zip(low["name"], low[d])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
