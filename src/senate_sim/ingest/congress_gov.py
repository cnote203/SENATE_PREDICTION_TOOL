"""Congress.gov API v3: Senate membership for a given Congress.

The member list endpoint is paged. Each page is cached as it arrives, so a
failed run can resume without re-downloading earlier pages.

AUDIT: field names below follow the documented v3 member schema. The first
live run should be checked against the raw payloads saved in data/raw/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

PAGE_SIZE = 250


def _senate_terms(member: dict) -> list[dict]:
    terms = member.get("terms")
    if isinstance(terms, dict):
        terms = terms.get("item", [])
    if not isinstance(terms, list):
        return []
    return [t for t in terms if str(t.get("chamber", "")).lower() == "senate"]


def parse_members_payload(members: list[dict], congress: int) -> pd.DataFrame:
    """Keep only members with a Senate term in the requested Congress."""
    rows = []
    for m in members:
        senate_in_congress = [
            t for t in _senate_terms(m)
            if t.get("congress") in (None, congress)
        ]
        if not senate_in_congress:
            continue
        rows.append(
            {
                "bioguide_id": m.get("bioguideId"),
                "name": m.get("name"),
                "state": m.get("state"),
                "api_party": m.get("partyName"),
            }
        )
    return pd.DataFrame(rows)


def fetch_senate_roster(
    congress: int = config.ROSTER_CONGRESS,
    cache_dir: Path = config.RAW_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    """Return one row per senator serving in the given Congress."""
    api_key = config.congress_api_key()
    url = f"{config.CONGRESS_API_BASE}/member/congress/{congress}"

    members: list[dict] = []
    offset = 0
    while True:
        params = {
            "format": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
            "api_key": api_key,
        }
        body = cached_get(url, params=params, cache_dir=cache_dir, refresh=refresh)
        payload = json.loads(body)
        members.extend(payload.get("members", []))
        if not payload.get("pagination", {}).get("next"):
            break
        offset += PAGE_SIZE

    roster = parse_members_payload(members, congress)
    if roster.empty:
        raise RuntimeError(
            f"No Senate members found for Congress {congress}. Check the raw "
            f"payloads in {cache_dir} against the field names in this module."
        )
    return roster
