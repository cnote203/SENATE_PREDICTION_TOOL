"""Build the baseline Senate roster: one row per senator with a caucus label.

Caucus is what the simulation should count for majority math. Party is kept
separately because two independents caucus with the Democrats.
"""
from __future__ import annotations

import pandas as pd

from senate_sim import config


def assign_caucus(df: pd.DataFrame) -> pd.DataFrame:
    """Add `caucus` ('D', 'R', or 'I') from the Congress.gov party label."""
    df = df.copy()

    def caucus(row) -> str:
        if row["bioguide_id"] in config.CAUCUS_WITH_DEMOCRATS:
            return "D"
        party = str(row.get("api_party") or "")
        if party.startswith("Democrat"):
            return "D"
        if party.startswith("Republican"):
            return "R"
        return "I"

    df["caucus"] = df.apply(caucus, axis=1)
    return df


def build_baseline(roster: pd.DataFrame, voteview: pd.DataFrame) -> pd.DataFrame:
    """Left-join Voteview ideology scores onto the roster and add caucus labels."""
    if roster["bioguide_id"].duplicated().any():
        dupes = roster.loc[roster["bioguide_id"].duplicated(), "bioguide_id"].tolist()
        raise ValueError(f"Duplicate Bioguide IDs in roster: {dupes}")

    merged = roster.merge(voteview, on="bioguide_id", how="left", validate="one_to_one")
    merged = assign_caucus(merged)
    return merged.sort_values(["state", "name"]).reset_index(drop=True)


def validate_baseline(df: pd.DataFrame) -> None:
    """Raise if the roster does not match the expected split or has missing data."""
    if len(df) != config.EXPECTED_TOTAL:
        raise ValueError(f"Expected {config.EXPECTED_TOTAL} senators, found {len(df)}.")

    counts = df["caucus"].value_counts().to_dict()
    for side, expected in config.EXPECTED_SPLIT.items():
        actual = counts.get(side, 0)
        if actual != expected:
            raise ValueError(
                f"Caucus '{side}' has {actual} senators; expected {expected}. "
                f"Full counts: {counts}"
            )

    missing_scores = df["nominate_dim1"].isna().sum()
    if missing_scores:
        # Freshmen have no DW-NOMINATE score until they have cast votes in the Congress.
        print(
            f"note: {missing_scores} senators have no Voteview score "
            "(expected for incoming freshmen)."
        )
