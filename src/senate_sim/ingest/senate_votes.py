"""senate.gov roll-call votes (XML), keyed to Bioguide IDs.

URL pattern (documented by senate.gov):
  https://www.senate.gov/legislative/LIS/roll_call_votes/vote{C}{S}/vote_{C}_{S}_{NNNNN}.xml

Each <member> carries lis_member_id (e.g. S313), which congress-legislators
maps to a Bioguide ID through id.lis. senate.gov is the authoritative source
and updates the same day; Voteview lags by days to weeks.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

VOTE_URL = (
    "https://www.senate.gov/legislative/LIS/roll_call_votes/"
    "vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.xml"
)

# Positions mapped to the binary outcome. Present and Not Voting are missing.
YEA = {"Yea", "Guilty"}
NAY = {"Nay", "Not Guilty"}


def _looks_like_vote(body: bytes) -> bool:
    return b"<roll_call_vote" in body[:2000]


def parse_vote_xml(body: bytes) -> tuple[dict, pd.DataFrame]:
    root = ET.fromstring(body)

    def text(path: str) -> str:
        node = root.find(path)
        return (node.text or "").strip() if node is not None else ""

    meta = {
        "congress": int(text("congress")),
        "session": int(text("session")),
        "roll": int(text("vote_number")),
        "date": text("vote_date"),
        "question": text("vote_question_text"),
        "document": text("vote_document_text"),
        "result": text("vote_result_text"),
        "majority_requirement": text("majority_requirement"),
        "yeas": int(text("count/yeas") or 0),
        "nays": int(text("count/nays") or 0),
    }
    rows = []
    for m in root.iter("member"):
        def f(tag: str) -> str:
            node = m.find(tag)
            return (node.text or "").strip() if node is not None else ""
        rows.append(
            {
                "lis_id": f("lis_member_id"),
                "party": f("party"),
                "state": f("state"),
                "vote_cast": f("vote_cast"),
            }
        )
    return meta, pd.DataFrame(rows)


def lis_to_bioguide(people: dict[str, dict]) -> dict[str, str]:
    return {
        p["id"]["lis"]: bid
        for bid, p in people.items()
        if p.get("id", {}).get("lis")
    }


def fetch_vote(
    congress: int, session: int, roll: int,
    cache_dir: Path = config.RAW_DIR, refresh: bool = False,
) -> tuple[dict, pd.DataFrame]:
    url = VOTE_URL.format(congress=congress, session=session, roll=roll)
    body = cached_get(url, cache_dir=cache_dir, refresh=refresh, is_usable=_looks_like_vote)
    if not _looks_like_vote(body):
        raise RuntimeError(f"senate.gov did not return a roll-call XML for {url}")
    return parse_vote_xml(body)


def code_votes(members: pd.DataFrame, lis_map: dict[str, str]) -> pd.DataFrame:
    """Add bioguide_id and a 1/0/NaN yea indicator. Present and Not Voting are NaN."""
    df = members.copy()
    df["bioguide_id"] = df["lis_id"].map(lis_map)
    df["yea"] = df["vote_cast"].map(lambda v: 1.0 if v in YEA else (0.0 if v in NAY else float("nan")))
    return df
