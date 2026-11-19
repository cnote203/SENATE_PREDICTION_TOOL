"""Fit a policy module's dimension formulas to real Senate roll calls.

Usage (PowerShell):
    python scripts\\build_roster.py        # baseline must exist
    python scripts\\calibrate.py [--module foreign_policy] [--refresh]

Reads data/manual/calibration_votes.csv, downloads each roll call from senate.gov
(cached in data/raw), and writes:
    data/calibration/<module>.json             fitted mappings used by score_senators.py
    data/calibration/<module>_deviations.csv   how far each senator sits from the fit
Commit both files so scoring is reproducible without network access.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config  # noqa: E402
from senate_sim.ingest import legislators, senate_votes, voteview  # noqa: E402
from senate_sim.policy import calibration  # noqa: E402

ITEMS_PATH = config.PROJECT_ROOT / "data" / "manual" / "calibration_votes.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="foreign_policy")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    module = importlib.import_module(f"senate_sim.policy.{args.module}").MODULE
    targets = [d.name for d in module.dimensions if d.calibrate]
    items = pd.read_csv(ITEMS_PATH)
    items = items[items["dimension"].isin(targets)].copy()
    items["item_id"] = (items["congress"].astype(str) + "-" + items["session"].astype(str)
                        + "-" + items["roll"].astype(str))

    baseline_path = config.PROCESSED_DIR / f"senate_baseline_{config.ROSTER_CONGRESS}.csv"
    if not baseline_path.exists():
        print(f"Missing {baseline_path}. Run scripts\\build_roster.py first.")
        return 1
    baseline = pd.read_csv(baseline_path, dtype={"bioguide_id": str})

    print("Loading congress-legislators for LIS-to-Bioguide mapping...")
    people = legislators.index_by_bioguide(
        legislators.fetch_json("legislators-historical.json", refresh=args.refresh),
        legislators.fetch_json("legislators-current.json", refresh=args.refresh),
    )
    lis_map = senate_votes.lis_to_bioguide(people)

    print(f"Fetching {len(items)} roll calls from senate.gov...")
    frames = []
    for _, it in items.iterrows():
        try:
            meta, members = senate_votes.fetch_vote(it["congress"], it["session"], it["roll"],
                                                    refresh=args.refresh)
        except Exception as exc:
            print(f"  {it['item_id']}: FAILED ({exc}); skipped")
            continue
        coded = senate_votes.code_votes(members, lis_map)
        unmapped = coded["bioguide_id"].isna().sum()
        print(f"  {it['item_id']:>11} {meta['yeas']:>3}-{meta['nays']:<3} {it['dimension']:<22} "
              f"{meta['question'][:38]:<38} {meta['document'][:30]}"
              + (f"  [{unmapped} unmapped]" if unmapped else ""))
        frames.append(coded.assign(item_id=it["item_id"]))
    if not frames:
        print("No roll calls downloaded.")
        return 1
    votes = pd.concat(frames, ignore_index=True)

    print("Loading Voteview ideology...")
    history = voteview.fetch_member_history(refresh=args.refresh)
    data = calibration.build_dataset(
        items[["item_id", "dimension", "plus_side", "family", "president_party"]], votes,
        history[["bioguide_id", "nominate_dim1", "nominate_dim2"]],
    )
    roster = baseline.rename(columns={"nominate_dim1": "d1", "nominate_dim2": "d2"})[["d1", "d2"]]
    roster["d2"] = roster["d2"].fillna(0.0)

    fits = []
    for dim in targets:
        fit = calibration.fit_dimension(data, dim, roster)
        fits.append(fit)
        b = fit.beta
        dropped = fit.items[fit.items["minority_share"] < calibration.LOPSIDED_CUTOFF]
        print(f"\n{dim}: {len(fit.items)} items, {int(fit.items['n'].sum())} votes"
              + (f", {len(dropped)} lopsided dropped" if len(dropped) else ""))
        print(f"  mapping: {b['d1']:+.2f}*d1 {b['d1_sq']:+.2f}*d1^2 {b['d2']:+.2f}*d2")
        if b["d1_sq"] < 0:
            print(f"  peaks at d1 = {-b['d1'] / (2 * b['d1_sq']):+.2f}")
        print(f"  president's-party effect: {fit.gamma:+.2f}"
              + ("" if fit.gamma_identified else " (not identified: items from one White House only)"))
        print(f"  senator spread sigma: {fit.sigma_score:.2f} score units; CV: {fit.cv}")

    out = module.calibration_path
    calibration.save(fits, out, {
        "module": module.name, "fitted_on": date.today().isoformat(),
        "items_file": ITEMS_PATH.name, "lopsided_cutoff": calibration.LOPSIDED_CUTOFF,
    })
    names = pd.concat([baseline[["bioguide_id", "name"]],
                       pd.DataFrame([{"bioguide_id": b, "name": legislators._name(p)}
                                     for b, p in people.items()])]).drop_duplicates("bioguide_id")
    dev = pd.concat([f.deviations for f in fits]).merge(names, on="bioguide_id", how="left")
    dev_path = out.with_name(f"{module.name}_deviations.csv")
    dev.round(3).to_csv(dev_path, index=False)
    print(f"\nWrote {out} and {dev_path}")

    existing = pd.read_csv(module.override_path) if module.override_path.exists() else pd.DataFrame(
        columns=["bioguide_id", "dimension"])
    have = set(zip(existing["bioguide_id"], existing["dimension"]))
    sitting = set(baseline["bioguide_id"])
    flags = dev[dev["suggest_override"] & dev["bioguide_id"].isin(sitting)]
    flags = flags[[(b, d) not in have for b, d in zip(flags["bioguide_id"], flags["dimension"])]]
    if not flags.empty:
        print("\nSenators who sit far from the fitted mapping and have no override yet:")
        for _, r in flags.sort_values(["dimension", "u_raw_score"]).iterrows():
            print(f"  {r['dimension']:<22} {r['name']:<28} {r['u_raw_score']:+.2f} "
                  f"(+-{r['se_raw_score']:.2f}, {int(r['n_votes'])} votes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
