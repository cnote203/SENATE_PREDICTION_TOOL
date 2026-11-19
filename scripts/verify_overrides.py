"""Check each override against the roll calls listed in its roll_calls column (Voteview by default).

Usage (PowerShell):
    python scripts\\verify_overrides.py [--module foreign_policy]

Prints each senator's recorded vote on every cited roll call (congress-session-roll),
so the evidence behind an override can be confirmed in one pass.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from senate_sim.ingest import legislators, senate_votes, vote_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", default="foreign_policy")
    parser.add_argument("--source", choices=["voteview", "senate"], default="voteview")
    args = parser.parse_args()
    module = importlib.import_module(f"senate_sim.policy.{args.module}").MODULE

    ov = pd.read_csv(module.override_path, dtype=str).fillna("")
    people = legislators.index_by_bioguide(
        legislators.fetch_json("legislators-historical.json"),
        legislators.fetch_json("legislators-current.json"),
    )
    source = vote_sources.make_source(args.source, senate_votes.lis_to_bioguide(people))
    cache: dict[str, pd.DataFrame] = {}
    for _, o in ov.iterrows():
        cited = [r for r in o["roll_calls"].split(";") if r]
        print(f"\n{o['name']} | {o['dimension']} = {o['score']} | verified: {o['verified']}")
        if not cited:
            print("  no roll calls cited")
            continue
        for rc in cited:
            if rc not in cache:
                c, s, n = (int(x) for x in rc.split("-"))
                try:
                    meta, members = source.get(c, s, n)
                    cache[rc] = members.assign(_q=f"{meta['question'][:30]} {meta['document'][:25]}",
                                               _t=f"{meta['yeas']}-{meta['nays']}")
                except Exception as exc:
                    print(f"  {rc}: could not fetch ({exc})")
                    continue
            m = cache[rc]
            row = m[m["bioguide_id"] == o["bioguide_id"]]
            cast = row["vote_cast"].iloc[0] if len(row) else "not a member"
            print(f"  {rc:>10}  {cast:<12} ({m['_t'].iloc[0]}) {m['_q'].iloc[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
