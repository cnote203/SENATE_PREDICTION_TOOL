"""unitedstates/congress-legislators: roster, IDs, Senate class, caucus, and service history.

Public-domain data maintained by GovTrack and others:
https://github.com/unitedstates/congress-legislators

Files used (JSON, gh-pages branch):
  legislators-current.json      sitting members, with every term served
  legislators-historical.json   everyone else (needed for returning ex-senators)
  committee-membership-current.json, committees-current.json   see committees.py
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

# Two Senate terms closer together than this count as continuous service.
CONTINUITY_GAP = timedelta(days=7)


def fetch_json(name: str, cache_dir: Path = config.RAW_DIR, refresh: bool = False):
    body = cached_get(f"{config.LEGISLATORS_BASE}/{name}", cache_dir=cache_dir, refresh=refresh)
    return json.loads(body)


def _d(value: str) -> date:
    return date.fromisoformat(value)


def _name(person: dict) -> str:
    n = person.get("name", {})
    return n.get("official_full") or f"{n.get('first', '')} {n.get('last', '')}".strip()


def index_by_bioguide(*people_lists: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for people in people_lists:
        for p in people:
            bid = p.get("id", {}).get("bioguide")
            if bid:
                out[bid] = p
    return out


def senators_from_current(current: list[dict]) -> pd.DataFrame:
    """One row per person whose latest term is a Senate term.

    No end-date filter: an appointed senator whose seat was decided in a special
    election stays listed until the winner is sworn in, and the seat changes
    file handles the swap.
    """
    rows = []
    for p in current:
        last = p["terms"][-1]
        if last.get("type") != "sen":
            continue
        ids = p.get("id", {})
        rows.append(
            {
                "bioguide_id": ids.get("bioguide"),
                "name": _name(p),
                "state": last.get("state"),
                "api_party": last.get("party"),
                "caucus_field": last.get("caucus"),
                "senate_class": last.get("class"),
                "term_end": last.get("end"),
                "lis_id": ids.get("lis"),
                "icpsr_id": ids.get("icpsr"),
                "fec_ids": ",".join(ids.get("fec", []) or []),
            }
        )
    return pd.DataFrame(rows)


def _days(start: str, end: str, cap: date) -> int:
    s, e = _d(start), min(_d(end), cap)
    return max((e - s).days, 0)


def service_summary(person: dict | None, incoming: bool, as_of: date) -> dict:
    """Seniority inputs for one senator as of the start of the new Congress.

    Senate seniority runs on continuous service. Earlier, broken Senate service
    and House service are the conventional tiebreakers, in that order.
    Incoming senators start their continuous service on `as_of`.
    AUDIT: special-election winners seated before January 3 get slightly earlier
    seniority in practice; this uses `as_of` for every incoming senator.
    """
    if person is None:
        return {"seniority_start": as_of.isoformat(), "prior_senate_days": 0, "prior_house_days": 0}

    terms = sorted(person.get("terms", []), key=lambda t: t["start"])
    house_days = sum(_days(t["start"], t["end"], as_of) for t in terms if t["type"] == "rep")

    runs: list[list[dict]] = []
    for t in (t for t in terms if t["type"] == "sen"):
        if runs and _d(t["start"]) - _d(runs[-1][-1]["end"]) <= CONTINUITY_GAP:
            runs[-1].append(t)
        else:
            runs.append([t])

    def run_days(run):
        return sum(_days(t["start"], t["end"], as_of) for t in run)

    if incoming or not runs:
        prior = sum(run_days(r) for r in runs)
        start = as_of
    else:
        prior = sum(run_days(r) for r in runs[:-1])
        start = _d(runs[-1][0]["start"])

    return {
        "seniority_start": start.isoformat(),
        "prior_senate_days": prior,
        "prior_house_days": house_days,
    }


def add_service(df: pd.DataFrame, people: dict[str, dict], as_of: str = config.ROSTER_START) -> pd.DataFrame:
    """Add seniority inputs and a Senate-wide seniority rank (1 = most senior)."""
    cutoff = _d(as_of)
    df = df.copy()
    incoming = df["incoming"] if "incoming" in df else pd.Series(False, index=df.index)
    summaries = [
        service_summary(people.get(bid), bool(inc), cutoff)
        for bid, inc in zip(df["bioguide_id"], incoming)
    ]
    df = pd.concat([df.reset_index(drop=True), pd.DataFrame(summaries)], axis=1)
    df["senate_years"] = (
        (cutoff - pd.to_datetime(df["seniority_start"]).dt.date).map(lambda d: d.days) / 365.25
    ).round(1)
    # AUDIT: the Senate's final tiebreaker is state population; name is a stand-in.
    order = df.sort_values(
        ["seniority_start", "prior_senate_days", "prior_house_days", "name"],
        ascending=[True, False, False, True],
    ).index
    df.loc[order, "seniority_rank"] = range(1, len(df) + 1)
    df["seniority_rank"] = df["seniority_rank"].astype(int)
    return df
