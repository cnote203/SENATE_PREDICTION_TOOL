"""Voteview bulk member data: DW-NOMINATE ideology scores keyed by Bioguide ID.

Reads Voteview's all-Congress, both-chamber member file so that incoming
senators with House service (or earlier Senate service) keep their most
recent score, and so prior Senate service can be counted for seniority.

DW-NOMINATE places House and Senate members on a roughly common scale, so a
House score is a usable starting point for a new senator. The `score_chamber`
column records where each score came from so the engine can treat House-derived
scores with more uncertainty.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

REQUIRED_COLUMNS = {
    "congress",
    "chamber",
    "bioguide_id",
    "nominate_dim1",
    "nominate_dim2",
    "nominate_number_of_votes",
}

OUTPUT_COLUMNS = [
    "bioguide_id",
    "nominate_dim1",
    "nominate_dim2",
    "nominate_votes",
    "score_congress",
    "score_chamber",
    "senate_congresses_served",
    "first_senate_congress",
]


def parse_all_members(raw: bytes, through_congress: int | None = None) -> pd.DataFrame:
    """Return one row per Bioguide ID with its latest score and Senate service history.

    through_congress caps which Congresses are read, so a projection never
    uses data from after the point it claims to start from.
    """
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Voteview file is missing columns: {sorted(missing)}")

    df = df[df["bioguide_id"].notna()].copy()
    df["chamber"] = df["chamber"].astype(str).str.strip().str.title()
    df = df[df["chamber"].isin(["Senate", "House"])]
    if through_congress is not None:
        df = df[df["congress"] <= through_congress]

    # Senate service: distinct Congresses with a Senate record.
    senate = df[df["chamber"] == "Senate"]
    service = senate.groupby("bioguide_id")["congress"].agg(
        senate_congresses_served="nunique", first_senate_congress="min"
    )

    # Latest score: newest Congress first; within it prefer the Senate, then most votes.
    scored = df[df["nominate_dim1"].notna()].copy()
    scored["_senate_first"] = (scored["chamber"] != "Senate").astype(int)
    scored = scored.sort_values(
        ["congress", "_senate_first", "nominate_number_of_votes"],
        ascending=[False, True, False],
    )
    latest = scored.drop_duplicates("bioguide_id", keep="first").set_index("bioguide_id")
    latest = pd.DataFrame(
        {
            "nominate_dim1": latest["nominate_dim1"],
            "nominate_dim2": latest["nominate_dim2"],
            "nominate_votes": latest["nominate_number_of_votes"],
            "score_congress": latest["congress"],
            "score_chamber": latest["chamber"],
        }
    )

    out = latest.join(service, how="outer")
    out["senate_congresses_served"] = out["senate_congresses_served"].fillna(0).astype(int)
    out = out.reset_index().rename(columns={"index": "bioguide_id"})
    return out[OUTPUT_COLUMNS]


def fetch_member_history(
    through_congress: int = config.VOTEVIEW_CONGRESS,
    cache_dir: Path = config.RAW_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    """Download (or read from cache) Voteview's all-Congress member file and summarize it."""
    raw = cached_get(config.VOTEVIEW_ALL_MEMBERS_URL, cache_dir=cache_dir, refresh=refresh)
    return parse_all_members(raw, through_congress=through_congress)
