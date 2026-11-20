"""Export model results for every sector as JSON for the web app (web/public/data).

Usage (PowerShell), after the pipeline has run:
    python scripts\\build_roster.py
    python scripts\\calibrate.py --module all
    python scripts\\score_senators.py --module all
    python scripts\\run_multicycle.py --president-2028 D
    python scripts\\run_multicycle.py --president-2028 R
    python scripts\\export_web.py [--runs 20000]

Writes:
    senators.json   roster, committees, donors, and scores per sector and dimension
    measures.json   every sector's measures in the 120th Senate under each White House
    timeline.json   120th-122nd Congress summaries for the D and R 2028 branches
    meta.json       sectors, dimensions, calibration summaries, data sources
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim import config, donors as donor_model, policy  # noqa: E402
from senate_sim.policy import calibration  # noqa: E402
from senate_sim.simulation import position_for, required_defectors, simulate  # noqa: E402

P = config.PROCESSED_DIR
N = config.ROSTER_CONGRESS
OUT = PROJECT_ROOT / "web" / "public" / "data"


def clean(v):
    """JSON-safe scalars: NaN to None, numpy to Python."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def load_scores(module) -> pd.DataFrame | None:
    path = P / f"scores_{module.name}_{N}.csv"
    return pd.read_csv(path, dtype={"bioguide_id": str}) if path.exists() else None


def senators(baseline, scores_by_module, seats, donors) -> list[dict]:
    held = seats[seats["status"] == "member"].copy()
    held["title"] = held["title"].fillna("")
    d = donors.set_index("bioguide_id") if donors is not None else None
    indexed = {name: s.set_index("bioguide_id") for name, s in scores_by_module.items()}
    out = []
    for _, b in baseline.iterrows():
        bid = b["bioguide_id"]
        mine = held[held["bioguide_id"] == bid]
        scores = {}
        for name, s in indexed.items():
            row = s.loc[bid]
            dims = [c[:-3] for c in s.columns if c.endswith("_sd")]
            scores[name] = {dim: {"score": clean(row[dim]), "sd": clean(row[f"{dim}_sd"]),
                                  "source": clean(row[f"{dim}_source"])} for dim in dims}
        out.append({
            "id": bid, "name": b["name"], "state": b["state"], "caucus": b["caucus"],
            "party": clean(b.get("api_party")), "class": clean(b.get("senate_class")),
            "seniority": clean(b.get("seniority_rank")), "years": clean(b.get("senate_years")),
            "incoming": bool(b.get("incoming", False)), "newToSenate": bool(b.get("new_to_senate", False)),
            "ideology": {"d1": clean(b.get("nominate_dim1")), "d2": clean(b.get("nominate_dim2")),
                         "from": clean(b.get("score_chamber"))},
            "scores": scores,
            "committees": [{"id": r["committee_id"], "name": r["committee_name"], "tier": r["tier"],
                            "title": r["title"]} for _, r in mine.iterrows()],
            "donors": None if d is None or bid not in d.index else {
                c[4:]: clean(d.loc[bid, c]) for c in d.columns if c.startswith("fec_")},
        })
    return out


def measures(scores_by_module, runs: int) -> list[dict]:
    out = []
    for module in policy.all_modules():
        scores = scores_by_module.get(module.name)
        if scores is None:
            continue
        cal = calibration.load(module.calibration_path)
        seats = {c: int((scores["caucus"] == c).sum()) for c in ("D", "R")}
        for key, m in module.measures.items():
            entry = {"id": f"{module.name}:{key}", "module": module.name, "name": m.name,
                     "dimension": m.dimension, "plusSide": m.plus_side,
                     "stages": [{"name": s.name, "threshold": s.threshold} for s in m.stages],
                     "vetoPossible": m.veto_possible, "notes": m.notes, "byPresident": {}}
            for pres in ("R", "D"):
                r = simulate(scores, m, pres, cal, runs=runs, seed=11)
                entry["byPresident"][pres] = {
                    "position": position_for(m, pres),
                    "pPassSenate": r["p_passes_senate"], "pEnacted": r["p_enacted"],
                    "pBothChambers": r.get("p_passes_both_chambers"),
                    "pOverride": r.get("p_senate_override_if_passed"),
                    "defectorsNeeded": required_defectors(seats[pres]) if "p_senate_override_if_passed" in r else None,
                    "stages": r["stages"],
                    "senatorYea": dict(zip(scores["bioguide_id"], r["senator_yea_prob"])),
                    "pivotal": r["pivotal_senators"],
                    "calibrated": r["parameters"]["calibrated"],
                    "gammaIdentified": r["parameters"]["gamma_identified"],
                }
            out.append(entry)
            print(f"  simulated {entry['id']}")
    return out


def timeline() -> dict:
    out = {}
    for branch in ("D", "R"):
        files = {k: P / f"multicycle_{branch}_{k}.csv" for k in ("congress", "measures_by_white_house", "leadership")}
        if not all(f.exists() for f in files.values()):
            continue
        c = pd.read_csv(files["congress"])
        m = pd.read_csv(files["measures_by_white_house"])
        if "module" not in m:
            has_prefix = m["measure"].astype(str).str.contains(":")
            # Results from before sectors were added carry bare foreign policy measure names.
            m.loc[~has_prefix, "measure"] = "foreign_policy:" + m.loc[~has_prefix, "measure"].astype(str)
            m["module"] = m["measure"].astype(str).str.split(":").str[0]
        l = pd.read_csv(files["leadership"])
        l["top_holders"] = l["top_holders"].map(ast.literal_eval)
        out[branch] = {
            "congresses": [{k: clean(v) for k, v in r.items()} for r in c.to_dict(orient="records")],
            "measures": [{k: clean(v) for k, v in r.items()} for r in m.to_dict(orient="records")],
            "leadership": [{"congress": int(r["congress"]), "post": r["post"],
                            "holders": {k: float(v) for k, v in r["top_holders"].items()}}
                           for _, r in l.iterrows()],
        }
    return out


def meta(committee_names: dict) -> dict:
    items_file = pd.read_csv(PROJECT_ROOT / "data" / "manual" / "calibration_votes.csv", dtype=str)
    modules = []
    for module in policy.all_modules():
        cal = calibration.load(module.calibration_path) or {}
        dims = []
        for d in module.dimensions:
            fit = cal.get(d.name)
            dims.append({
                "id": d.name, "label": d.label, "short": d.short, "lowTag": d.low_tag, "highTag": d.high_tag,
                "low": d.low, "high": d.high, "calibrated": bool(fit),
                "gamma": clean(fit["gamma"]) if fit else None,
                "gammaIdentified": bool(fit["gamma_identified"]) if fit else False,
                "sigma": clean(fit["sigma_score"]) if fit else None,
                "cv": fit.get("cv") if fit else None,
                "rollCalls": [] if not fit else [
                    {"id": it["item_id"], "date": clean(it.get("date")), "family": it["family"],
                     "minorityShare": clean(it.get("minority_share"))} for it in fit["items"]],
                "plannedRollCalls": int((items_file["dimension"] == d.name).sum()),
            })
        modules.append({"id": module.name, "label": module.label, "dimensions": dims,
                        "committees": [{"id": c, "name": committee_names.get(c, c)} for c in module.committees]})
    effects_path = P / "donor_effects.csv"
    effects = pd.read_csv(effects_path) if effects_path.exists() else pd.DataFrame(columns=["category"])
    donor_categories = [
        {"id": cid, "label": label, "sectors": sectors,
         "tests": [{"dimension": e["dimension"], "supported": bool(e["supports_hypothesis"]),
                    "r": clean(e["r"]), "p": clean(e.get("p_holm", e["p_value"]))}
                   for _, e in effects[effects["category"] == cid].iterrows()]}
        for cid, (label, sectors) in donor_model.CATEGORIES.items()
    ]
    return {
        "generated": date.today().isoformat(),
        "congress": N,
        "modules": modules,
        "donorCategories": donor_categories,
        "sources": [
            {"name": "unitedstates/congress-legislators", "use": "roster, IDs, committees, service"},
            {"name": "Voteview", "use": "DW-NOMINATE and roll-call votes"},
            {"name": "OpenFEC", "use": "PAC contributions"},
            {"name": "2024 county presidential results (tonmcg)", "use": "state partisan lean"},
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=20000)
    args = ap.parse_args()

    baseline = pd.read_csv(P / f"senate_baseline_{N}.csv", dtype={"bioguide_id": str})
    seats = pd.read_csv(P / f"committee_assignments_{N}.csv", dtype={"bioguide_id": str})
    donors_path = P / f"donors_{N}.csv"
    donors = pd.read_csv(donors_path, dtype={"bioguide_id": str}) if donors_path.exists() else None
    scores_by_module = {}
    for module in policy.all_modules():
        s = load_scores(module)
        if s is None:
            print(f"note: no scores for {module.name}; run score_senators.py --module all")
        else:
            scores_by_module[module.name] = s
    committee_names = seats.drop_duplicates("committee_id").set_index("committee_id")["committee_name"].to_dict()

    OUT.mkdir(parents=True, exist_ok=True)
    payloads = {
        "senators.json": senators(baseline, scores_by_module, seats, donors),
        "measures.json": measures(scores_by_module, args.runs),
        "timeline.json": timeline(),
        "meta.json": meta(committee_names),
    }
    for name, data in payloads.items():
        (OUT / name).write_text(json.dumps(data, separators=(",", ":"), default=clean))
        print(f"wrote web/public/data/{name} ({(OUT / name).stat().st_size / 1024:.0f} KB)")
    if not payloads["timeline.json"]:
        print("note: no multi-cycle results found; run scripts\\run_multicycle.py for both branches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
