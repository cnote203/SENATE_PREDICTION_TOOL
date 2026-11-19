"""Congress.gov API v3: Senate membership for a given Congress.

The member list endpoint is paged. Each page is cached as it arrives, so a
failed run can resume without re-downloading earlier pages. Pages with no
members are never cached: before a Congress convenes, Congress.gov answers
with an empty list, and that answer must not stick once real data exists.

AUDIT: field names below follow the documented v3 member schema. Check them
against the raw payloads saved in data/raw/ after the first successful run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

PAGE_SIZE = 250


class EmptyCongressError(RuntimeError):
    """Congress.gov returned no members, usually because the Congress has not convened."""


def _has_members(body: bytes) -> bool:
    try:
        return bool(json.loads(body).get("members"))
    except (ValueError, AttributeError):
        return False


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
    return pd.DataFrame(rows, columns=["bioguide_id", "name", "state", "api_party"])


def fetch_senate_roster(
    congress: int = config.ROSTER_CONGRESS,
    current_only: bool = False,
    cache_dir: Path = config.RAW_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    """Return one row per senator serving in the given Congress.

    current_only=True asks Congress.gov for sitting members only, which drops
    senators who left mid-Congress. Use it for the Congress now in session.
    """
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
        if current_only:
            params["currentMember"] = "true"
        body = cached_get(
            url, params=params, cache_dir=cache_dir, refresh=refresh, is_usable=_has_members
        )
        payload = json.loads(body)
        members.extend(payload.get("members", []))
        if not payload.get("pagination", {}).get("next"):
            break
        offset += PAGE_SIZE

    if not members:
        raise EmptyCongressError(
            f"Congress.gov lists no members for the {congress}th Congress yet."
        )

    roster = parse_members_payload(members, congress)
    if roster.empty:
        raise RuntimeError(
            f"Congress.gov returned {len(members)} members for Congress {congress}, but "
            f"none matched as senators. Check the raw payloads in {cache_dir} against "
            "the field names in this module."
        )
    return roster
