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
from senate_sim.ingest import legislators, senate_votes, vote_sources, voteview  # noqa: E402
from senate_sim.policy import calibration  # noqa: E402

ITEMS_PATH = config.PROJECT_ROOT / "data" / "manual" / "calibration_votes.csv"


def _run(args) -> int:

    module = importlib.import_module(f"senate_sim.policy.{args.module}").MODULE
    targets = [d.name for d in module.dimensions if d.calibrate]
    if not targets:
        print(f"{module.name}: no dimensions are calibrated (no usable roll calls); nothing to fit.")
        return 0
    items = pd.read_csv(ITEMS_PATH, dtype={"bill": str, "question": str})
    items = items[items["dimension"].isin(targets)].copy()
    for col in ("bill", "question"):
        if col not in items:
            items[col] = ""
        items[col] = items[col].fillna("")

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

    source = vote_sources.make_source(args.source, lis_map, refresh=args.refresh)

    # Rows without a roll number are looked up by bill and question (Voteview only),
    # so a citation can never point at the wrong vote.
    rows = []
    for _, it in items.iterrows():
        if pd.notna(it["roll"]) and str(it["roll"]).strip() != "":
            rows.append({**it.to_dict(), "session": int(it["session"]), "roll": int(it["roll"])})
            continue
        try:
            hits = source.find(int(it["congress"]), it["bill"], it["question"] or None)
        except Exception as exc:
            print(f"  {it['bill']}: lookup failed ({exc}); skipped")
            continue
        if not hits:
            print(f"  {it['bill']} /{it['question']}/: no matching Senate roll call (Voteview may lag); skipped")
        for h in hits:
            rows.append({**it.to_dict(), "session": h["session"], "roll": h["roll"]})
    items = pd.DataFrame(rows)
    if items.empty:
        print("No roll calls to fit.")
        return 1
    items["item_id"] = (items["congress"].astype(int).astype(str) + "-" + items["session"].astype(str)
                        + "-" + items["roll"].astype(str))
    items = items.drop_duplicates("item_id")
    print(f"Reading {len(items)} roll calls from {source.name}...")
    frames, failed, dates = [], 0, {}
    for _, it in items.iterrows():
        try:
            meta, coded = source.get(int(it["congress"]), int(it["session"]), int(it["roll"]))
        except Exception as exc:
            print(f"  {it['item_id']}: FAILED ({exc}); skipped")
            failed += 1
            if failed >= 3 and not frames:
                print("Three failures before any success; stopping. Try the other --source.")
                return 1
            continue
        if it["bill"] and source.name == "voteview" and \
                vote_sources.normalize_bill(meta["document"]) != vote_sources.normalize_bill(it["bill"]):
            print(f"  {it['item_id']}: Voteview lists bill {meta['document']!r}, expected {it['bill']!r}; skipped")
            continue
        dates[it["item_id"]] = str(meta.get("date", ""))[:10]
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
    items["date"] = items["item_id"].map(dates).where(lambda d: d.str.len() == 10, items["date"])
    data = calibration.build_dataset(
        items[["item_id", "dimension", "plus_side", "family", "president_party", "date"]], votes,
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
        if b["d1_sq"] < -0.3 and -1 <= -b["d1"] / (2 * b["d1_sq"]) <= 1:
            print(f"  peaks at d1 = {-b['d1'] / (2 * b['d1_sq']):+.2f}")
        if fit.thin:
            print("  thin dimension: curve-shape terms held to a tighter prior")
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
        columns=["bioguide_id", "dimension", "score"])
    checks = []
    for fit in fits:
        ov = existing[existing["dimension"] == fit.dimension].set_index("bioguide_id")["score"].to_dict()
        checks.append(calibration.consistency(data, fit, ov))
    checks = pd.concat(checks).merge(names, on="bioguide_id", how="left")
    checks.round(3).to_csv(out.with_name(f"{module.name}_consistency.csv"), index=False)
    bad = checks[checks["contradiction"] & checks["bioguide_id"].isin(set(baseline["bioguide_id"]))]
    if not bad.empty:
        print("\nScores that contradict actual votes (observed vs predicted share of +2-side votes):")
        for _, r in bad.sort_values(["dimension", "gap"]).iterrows():
            tag = "override" if r["has_override"] else "fitted"
            print(f"  {r['dimension']:<22} {r['name']:<28} observed {r['observed']:.2f} vs "
                  f"predicted {r['predicted']:.2f} ({int(r['n_votes'])} votes, {tag})")
        fresh = bad[~bad["has_override"]]
        if not fresh.empty:
            by_dim = {f.dimension: f for f in fits}
            print("\nDraft override rows (vote-matched, unshrunk). Check the roll calls, write the "
                  f"evidence, set verified, then paste into {module.override_path.name}:")
            for _, r in fresh.sort_values(["dimension", "name"]).iterrows():
                sc, items = calibration.vote_matched_score(data, by_dim[r["dimension"]], r["bioguide_id"])
                print(f"{r['bioguide_id']},{r['name']},{r['dimension']},{sc:+.1f},0.5,"
                      f"\"TODO: why their votes break from the curve\",{';'.join(items)},no")
    else:
        print("\nNo sitting senator's score contradicts their votes by 0.4 or more.")
    redundant = checks[checks["has_override"] & (checks["n_votes"] >= 5) & ~checks["contradiction"]]
    if not redundant.empty:
        print("\nOverrides on senators with 5+ votes on that dimension (their own votes already set "
              "the score; the override is optional):")
        for _, r in redundant.sort_values(["dimension", "name"]).iterrows():
            print(f"  {r['dimension']:<22} {r['name']}")
    return 0



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="foreign_policy", help="sector to fit, or 'all'")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--source", choices=["voteview", "senate"], default="voteview",
                        help="where to read individual votes (senate.gov often refuses scripts)")
    args = parser.parse_args()
    if args.module != "all":
        return _run(args)
    from senate_sim import policy
    status = 0
    for name in policy.MODULE_NAMES:
        print(f"\n===== {name} =====")
        args.module = name
        status = _run(args) or status
    return status


if __name__ == "__main__":
    raise SystemExit(main())
