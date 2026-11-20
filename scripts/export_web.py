"""Export model results as JSON for the web app (web/public/data).

Usage (PowerShell), after the pipeline has run:
    python scripts\\build_roster.py
    python scripts\\calibrate.py
    python scripts\\score_senators.py
    python scripts\\run_multicycle.py --president-2028 D
    python scripts\\run_multicycle.py --president-2028 R
    python scripts\\export_web.py [--runs 20000]

Writes:
    senators.json   roster, scores with uncertainty and source, committees, donors
    measures.json   every preset simulated in the 120th Senate under each White House:
                    stage odds, yea distribution, per-senator Yea probability, pivots
    timeline.json   120th-122nd Congress summaries for the D and R 2028 branches
    meta.json       dimensions, calibration summary, roll calls, data sources
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

from senate_sim import config  # noqa: E402
from senate_sim.policy import calibration, foreign_policy  # noqa: E402
from senate_sim.simulation import PRESETS, required_defectors, simulate  # noqa: E402

P = config.PROCESSED_DIR
N = config.ROSTER_CONGRESS
OUT = PROJECT_ROOT / "web" / "public" / "data"
MODULE = foreign_policy.MODULE


def clean(v):
    """JSON-safe scalars: NaN to None, numpy to Python."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def senators(baseline: pd.DataFrame, scores: pd.DataFrame, seats: pd.DataFrame,
             donors: pd.DataFrame | None) -> list[dict]:
    dims = MODULE.dimension_names
    s = scores.set_index("bioguide_id")
    held = seats[seats["status"] == "member"].copy()
    held["title"] = held["title"].fillna("")
    d = donors.set_index("bioguide_id") if donors is not None else None
    out = []
    for _, b in baseline.iterrows():
        bid = b["bioguide_id"]
        row = s.loc[bid]
        mine = held[held["bioguide_id"] == bid]
        out.append({
            "id": bid,
            "name": b["name"],
            "state": b["state"],
            "caucus": b["caucus"],
            "party": clean(b.get("api_party")),
            "class": clean(b.get("senate_class")),
            "seniority": clean(b.get("seniority_rank")),
            "years": clean(b.get("senate_years")),
            "incoming": bool(b.get("incoming", False)),
            "newToSenate": bool(b.get("new_to_senate", False)),
            "ideology": {"d1": clean(b.get("nominate_dim1")), "d2": clean(b.get("nominate_dim2")),
                         "from": clean(b.get("score_chamber"))},
            "scores": {dim: {"score": clean(row[dim]), "sd": clean(row[f"{dim}_sd"]),
                             "source": clean(row[f"{dim}_source"])} for dim in dims},
            "committees": [{"id": r["committee_id"], "name": r["committee_name"], "tier": r["tier"],
                            "title": r["title"]} for _, r in mine.iterrows()],
            "donors": None if d is None or bid not in d.index else {
                c[4:]: clean(d.loc[bid, c]) for c in d.columns if c.startswith("fec_")},
        })
    return out


def measures(scores: pd.DataFrame, cal: dict | None, runs: int) -> list[dict]:
    out = []
    seats = {c: int((scores["caucus"] == c).sum()) for c in ("D", "R")}
    for key, m in PRESETS.items():
        entry = {"id": key, "name": m.name, "dimension": m.dimension, "plusSide": m.plus_side,
                 "stages": [{"name": s.name, "threshold": s.threshold} for s in m.stages],
                 "presidentPosition": m.president_position, "vetoPossible": m.veto_possible,
                 "notes": m.notes, "byPresident": {}}
        for pres in ("R", "D"):
            r = simulate(scores, m, pres, cal, runs=runs, seed=11)
            entry["byPresident"][pres] = {
                "pPassSenate": r["p_passes_senate"],
                "pEnacted": r["p_enacted"],
                "pBothChambers": r.get("p_passes_both_chambers"),
                "pOverride": r.get("p_senate_override_if_passed"),
                "defectorsNeeded": required_defectors(seats[pres]) if m.veto_possible else None,
                "stages": r["stages"],
                "senatorYea": dict(zip(scores["bioguide_id"], r["senator_yea_prob"])),
                "pivotal": r["pivotal_senators"],
                "calibrated": r["parameters"]["calibrated"],
                "gammaIdentified": r["parameters"]["gamma_identified"],
            }
        out.append(entry)
    return out


def timeline() -> dict:
    out = {}
    for branch in ("D", "R"):
        files = {k: P / f"multicycle_{branch}_{k}.csv" for k in ("congress", "measures_by_white_house", "leadership")}
        if not all(f.exists() for f in files.values()):
            continue
        c = pd.read_csv(files["congress"])
        m = pd.read_csv(files["measures_by_white_house"])
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


def meta(cal: dict | None) -> dict:
    items_file = pd.read_csv(PROJECT_ROOT / "data" / "manual" / "calibration_votes.csv")
    items_file["item_id"] = (items_file["congress"].astype(str) + "-" + items_file["session"].astype(str)
                             + "-" + items_file["roll"].astype(str))
    dims = []
    for d in MODULE.dimensions:
        fit = (cal or {}).get(d.name)
        dims.append({
            "id": d.name, "low": d.low, "high": d.high, "calibrated": bool(fit),
            "gamma": clean(fit["gamma"]) if fit else None,
            "gammaIdentified": bool(fit["gamma_identified"]) if fit else False,
            "sigma": clean(fit["sigma_score"]) if fit else None,
            "cv": fit.get("cv") if fit else None,
            "rollCalls": [] if not fit else [
                {"id": it["item_id"], "date": clean(it.get("date")), "family": it["family"],
                 "minorityShare": clean(it.get("minority_share")),
                 "measure": items_file.set_index("item_id")["measure"].get(it["item_id"]),
                 "note": items_file.set_index("item_id")["note"].get(it["item_id"])}
                for it in fit["items"]],
        })
    return {
        "generated": date.today().isoformat(),
        "congress": N,
        "module": MODULE.name,
        "dimensions": dims,
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
    scores = pd.read_csv(P / f"scores_{MODULE.name}_{N}.csv", dtype={"bioguide_id": str})
    seats = pd.read_csv(P / f"committee_assignments_{N}.csv", dtype={"bioguide_id": str})
    donors_path = P / f"donors_{N}.csv"
    donors = pd.read_csv(donors_path, dtype={"bioguide_id": str}) if donors_path.exists() else None
    cal = calibration.load(MODULE.calibration_path)

    OUT.mkdir(parents=True, exist_ok=True)
    payloads = {
        "senators.json": senators(baseline, scores, seats, donors),
        "measures.json": measures(scores, cal, args.runs),
        "timeline.json": timeline(),
        "meta.json": meta(cal),
    }
    for name, data in payloads.items():
        (OUT / name).write_text(json.dumps(data, separators=(",", ":"), default=clean))
        print(f"wrote web/public/data/{name} ({(OUT / name).stat().st_size / 1024:.0f} KB)")
    if not payloads["timeline.json"]:
        print("note: no multi-cycle results found; run scripts\\run_multicycle.py for both branches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
