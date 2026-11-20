"""Pull PAC contributions to senators from OpenFEC and test whether they explain votes.

Usage (PowerShell):
    python scripts\\fetch_donors.py --resolve   # step 1: find PAC committee IDs for new categories, then review
    python scripts\\fetch_donors.py             # step 2: pull contributions and analyse

Step 1 adds to data/manual/donor_pacs.csv. It only searches name patterns that
are not in the file yet, so rows you have already reviewed keep their include
setting (--resolve-all searches everything again). Check the new matches and set
include to no for anything that is not the company's or group's own PAC.
Step 2 writes data/processed/donors_120.csv and data/processed/donor_effects.csv.

Uses OPENFEC_API_KEY, or CONGRESS_API_KEY (the same api.data.gov key works).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config, donors  # noqa: E402
from senate_sim.ingest import openfec  # noqa: E402

MANUAL = config.PROJECT_ROOT / "data" / "manual"
N = config.ROSTER_CONGRESS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="store_true", help="search FEC for PACs not yet in donor_pacs.csv")
    parser.add_argument("--resolve-all", action="store_true", help="search every pattern again and rebuild the file")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    get = openfec.make_getter(refresh=args.refresh)

    pacs_path = MANUAL / "donor_pacs.csv"
    cats = pd.read_csv(MANUAL / "donor_categories.csv")
    unknown = sorted(set(cats["category"]) - set(donors.CATEGORIES))
    if unknown:
        print(f"donor_categories.csv uses categories with no label in donors.CATEGORIES: {', '.join(unknown)}")
        return 1
    if args.resolve or args.resolve_all or not pacs_path.exists():
        existing = None if args.resolve_all or not pacs_path.exists() else pd.read_csv(pacs_path, dtype=str)
        todo = cats if existing is None else cats[~cats["pattern"].isin(set(existing["pattern"]))]
        print(f"Searching FEC for {len(todo)} PAC name patterns...")
        found = openfec.resolve_pacs(get, todo)
        pacs = donors.merge_pacs(existing, found)
        pacs.to_csv(pacs_path, index=False)
        new = len(pacs) - (0 if existing is None else len(existing))
        print(f"Wrote {pacs_path.name}: {new} new candidate committees, {len(pacs)} in total")
        print(pacs.groupby(["category", "include"]).size().to_string())
        print("\nReview the new rows (set include to yes/no), then run without --resolve.")
        return 0

    pacs = pd.read_csv(pacs_path, dtype=str)
    baseline = pd.read_csv(config.PROCESSED_DIR / f"senate_baseline_{N}.csv", dtype={"bioguide_id": str})
    print(f"Mapping {len(baseline)} senators to their FEC campaign committees...")
    committees = openfec.senator_committees(get, baseline)
    missing = sorted(set(baseline["bioguide_id"]) - set(committees["bioguide_id"]))
    if missing:
        names = baseline.set_index("bioguide_id").loc[missing, "name"].tolist()
        print(f"  no FEC committee found for {len(missing)}: {', '.join(names)}")

    included = pacs[pacs["include"].str.lower() == "yes"]
    print(f"Pulling contributions from {len(included)} PACs for cycles {openfec.CYCLES}...")
    gifts = openfec.pac_to_recipients(get, pacs)
    totals = openfec.senator_totals(gifts, committees)
    out = baseline[["bioguide_id", "name", "state", "caucus"]].merge(totals, on="bioguide_id", how="left")
    money = [c for c in out.columns if c.startswith("fec_") or c.startswith("npacs_")]
    out[money] = out[money].fillna(0)
    out.to_csv(config.PROCESSED_DIR / f"donors_{N}.csv", index=False)

    for col in [c for c in out.columns if c.startswith("fec_")]:
        top = out.nlargest(5, col)
        print(f"\n{col[4:]}: total ${out[col].sum():,.0f}; by caucus "
              + ", ".join(f"{k} ${v:,.0f}" for k, v in out.groupby('caucus')[col].mean().items()) + " (mean)")
        print("  top: " + ", ".join(f"{n} ${v:,.0f}" for n, v in zip(top["name"], top[col])))

    dev_paths = sorted((config.PROJECT_ROOT / "data" / "calibration").glob("*_deviations.csv"))
    if dev_paths:
        deviations = pd.concat([pd.read_csv(p, dtype={"bioguide_id": str}) for p in dev_paths], ignore_index=True)
        effects = donors.test_donor_effects(out, deviations, baseline[["bioguide_id", "caucus"]])
        effects.to_csv(config.PROCESSED_DIR / "donor_effects.csv", index=False)
        print("\nDo PAC dollars explain votes beyond ideology? (within caucus)")
        for _, e in effects.iterrows():
            verdict = "yes" if e["supports_hypothesis"] else "no"
            print(f"  {e['category']:<18} -> {e['dimension']:<28} slope {e['slope_per_log_dollar']:+.3f} "
                  f"per log-dollar, r={e['r']:+.2f}, p={e['p_value']:.3f} (Holm {e['p_holm']:.3f}), "
                  f"n={e['n']} -> {verdict}")
        print("  (Holm-adjusted within each sector, so adding tests does not add chance findings.)")
    else:
        print("\nRun scripts\\calibrate.py first to test donor effects against vote deviations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
