"""Voteview bulk member data: DW-NOMINATE ideology scores keyed by Bioguide ID."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from senate_sim import config
from senate_sim.ingest.http import cached_get

REQUIRED_COLUMNS = {
    "congress",
    "chamber",
    "icpsr",
    "state_abbrev",
    "party_code",
    "bioname",
    "bioguide_id",
    "nominate_dim1",
    "nominate_dim2",
    "nominate_number_of_votes",
}

# Voteview party codes (subset relevant to the Senate).
VOTEVIEW_PARTY = {100: "Democrat", 200: "Republican", 328: "Independent"}


def parse_members_csv(raw: bytes, congress: int) -> pd.DataFrame:
    """Parse a Voteview members CSV into one row per senator for the given Congress."""
    df = pd.read_csv(io.BytesIO(raw))
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Voteview file is missing columns: {sorted(missing)}")

    senate = df[df["chamber"].astype(str).str.upper().isin(["SEN", "SENATE"])]
    senate = senate[senate["congress"] == congress].copy()

    # Senators who left mid-Congress appear once per seat holder. Keep the
    # record with the most roll-call votes so each Bioguide ID appears once.
    senate = senate.sort_values("nominate_number_of_votes", ascending=False)
    senate = senate.drop_duplicates(subset="bioguide_id", keep="first")

    out = pd.DataFrame(
        {
            "bioguide_id": senate["bioguide_id"],
            "icpsr": senate["icpsr"],
            "vv_state": senate["state_abbrev"],
            "vv_party": senate["party_code"].map(VOTEVIEW_PARTY),
            "nominate_dim1": senate["nominate_dim1"],
            "nominate_dim2": senate["nominate_dim2"],
            "nominate_votes": senate["nominate_number_of_votes"],
        }
    )
    return out.reset_index(drop=True)


def fetch_senate_members(
    congress: int = config.VOTEVIEW_CONGRESS,
    cache_dir: Path = config.RAW_DIR,
    refresh: bool = False,
) -> pd.DataFrame:
    """Download (or read from cache) Voteview's Senate member file for one Congress."""
    url = config.VOTEVIEW_MEMBERS_URL.format(congress=congress)
    raw = cached_get(url, cache_dir=cache_dir, refresh=refresh)
    return parse_members_csv(raw, congress)
