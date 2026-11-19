"""OpenFEC API: PAC contributions to senators' campaign committees.

FEC data has no industry codes, so donor categories come from a curated list of
PAC name patterns (data/manual/donor_categories.csv), resolved to FEC committee
IDs and reviewed by hand (data/manual/donor_pacs.csv).

Endpoints used (https://api.open.fec.gov/developers/):
  /committees/                          search committees by name and type
  /candidate/{candidate_id}/committees/ a candidate's principal and authorized committees
  /candidates/search/                   find a candidate ID by name (incoming senators)
  /schedules/schedule_b/by_recipient_id/  a committee's disbursements, totalled by recipient
                                          committee and two-year cycle

Only direct PAC-to-campaign contributions are counted. Super PAC independent
expenditures (e.g. United Democracy Project) and earmarked individual
contributions bundled by conduits are not included.

Authentication uses an api.data.gov key: OPENFEC_API_KEY, else CONGRESS_API_KEY
(the same key works for both), else DEMO_KEY (very low rate limit).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

BASE = "https://api.open.fec.gov/v1"
PAC_TYPES = ["Q", "N", "V", "W"]  # qualified and non-qualified PACs, with or without non-contribution accounts
CYCLES = [2022, 2024, 2026]       # covers a full six-year Senate term

JsonGetter = Callable[[str, dict], dict]


def api_key() -> str:
    for env in (config.OPENFEC_API_KEY_ENV, config.CONGRESS_API_KEY_ENV):
        if os.environ.get(env, "").strip():
            return os.environ[env].strip()
    print("warning: no OPENFEC_API_KEY or CONGRESS_API_KEY set; using DEMO_KEY (heavily rate limited)")
    return "DEMO_KEY"


def make_getter(refresh: bool = False, cache_dir: Path = config.RAW_DIR, pause: float = 0.1) -> JsonGetter:
    key = api_key()

    def get(path: str, params: dict) -> dict:
        body = cached_get(f"{BASE}{path}", params={**params, "api_key": key},
                          cache_dir=cache_dir, refresh=refresh,
                          is_usable=lambda b: b.lstrip().startswith(b"{"))
        time.sleep(pause)
        return json.loads(body)
    return get


def _pages(get: JsonGetter, path: str, params: dict, max_pages: int = 50):
    page = 1
    while True:
        data = get(path, {**params, "page": page, "per_page": 100})
        yield from data.get("results", [])
        pages = data.get("pagination", {}).get("pages") or 1
        if page >= pages or page >= max_pages:
            break
        page += 1


def resolve_pacs(get: JsonGetter, categories: pd.DataFrame) -> pd.DataFrame:
    """Search FEC committees for each pattern and keep PACs whose names match it."""
    rows = []
    for _, c in categories.iterrows():
        rx = re.compile(c["pattern"], re.I)
        for r in _pages(get, "/committees/", {"q": c["search"], "committee_type": PAC_TYPES}, max_pages=3):
            name = r.get("name") or ""
            if not rx.search(name):
                continue
            rows.append({
                "category": c["category"], "pattern": c["pattern"],
                "committee_id": r.get("committee_id"), "name": name,
                "committee_type": r.get("committee_type"), "designation": r.get("designation"),
                "last_cycle": max(r.get("cycles") or [0]),
                # Leadership PACs and inactive committees are left for review, off by default.
                "include": "no" if r.get("designation") == "D" or max(r.get("cycles") or [0]) < 2022 else "yes",
            })
    out = pd.DataFrame(rows).drop_duplicates("committee_id") if rows else pd.DataFrame(
        columns=["category", "pattern", "committee_id", "name", "committee_type", "designation",
                 "last_cycle", "include"])
    return out.sort_values(["category", "name"]).reset_index(drop=True)


def senator_committees(get: JsonGetter, roster: pd.DataFrame) -> pd.DataFrame:
    """Map each senator to the principal/authorized committees of every FEC candidate ID they hold.

    Incoming senators without FEC IDs on file are looked up by name among 2026 Senate candidates.
    """
    rows = []
    for _, s in roster.iterrows():
        ids = [i for i in str(s.get("fec_ids") or "").split(",") if i]
        how = "fec_ids"
        if not ids:
            hits = list(_pages(get, "/candidates/search/",
                               {"q": s["name"], "office": "S", "state": s["state"], "election_year": 2026},
                               max_pages=1))
            ids = [h["candidate_id"] for h in hits[:1]]
            how = "name_search"
        for cid in ids:
            for c in _pages(get, f"/candidate/{cid}/committees/", {"designation": ["P", "A"]}, max_pages=2):
                rows.append({"bioguide_id": s["bioguide_id"], "candidate_id": cid,
                             "committee_id": c.get("committee_id"), "resolved_by": how})
    return pd.DataFrame(rows, columns=["bioguide_id", "candidate_id", "committee_id", "resolved_by"]
                        ).drop_duplicates(["bioguide_id", "committee_id"])


def pac_to_recipients(get: JsonGetter, pacs: pd.DataFrame, cycles=CYCLES) -> pd.DataFrame:
    """Disbursement totals from each included PAC to each recipient committee, by cycle."""
    rows = []
    for _, p in pacs[pacs["include"].str.lower() == "yes"].iterrows():
        for cycle in cycles:
            for r in _pages(get, "/schedules/schedule_b/by_recipient_id/",
                            {"committee_id": p["committee_id"], "cycle": cycle}):
                rows.append({"category": p["category"], "pac_id": p["committee_id"], "cycle": cycle,
                             "recipient_id": r.get("recipient_id"), "total": float(r.get("total") or 0)})
    return pd.DataFrame(rows, columns=["category", "pac_id", "cycle", "recipient_id", "total"])


def senator_totals(gifts: pd.DataFrame, committees: pd.DataFrame) -> pd.DataFrame:
    """Total PAC money per senator and category (all cycles, all their committees)."""
    m = gifts.merge(committees, left_on="recipient_id", right_on="committee_id")
    g = m.groupby(["bioguide_id", "category"]).agg(total=("total", "sum"), n_pacs=("pac_id", "nunique"))
    wide = g["total"].unstack(fill_value=0.0).add_prefix("fec_")
    pacs = g["n_pacs"].unstack(fill_value=0).add_prefix("npacs_")
    return wide.join(pacs).reset_index()
