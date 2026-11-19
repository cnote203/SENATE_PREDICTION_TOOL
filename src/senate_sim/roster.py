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
        if bool(row.get("caucus_with_d", False)) is True:
            return "D"
        caucus_field = row.get("caucus_field")
        if isinstance(caucus_field, str) and caucus_field:
            return "D" if caucus_field.startswith("Democrat") else (
                "R" if caucus_field.startswith("Republican") else "I")
        party = str(row.get("api_party") or "")
        if party.startswith("Democrat"):
            return "D"
        if party.startswith("Republican"):
            return "R"
        return "I"

    df["caucus"] = df.apply(caucus, axis=1)
    return df


def build_baseline(roster: pd.DataFrame, voteview: pd.DataFrame) -> pd.DataFrame:
    """Left-join Voteview history onto the roster and add caucus and service labels.

    Adds:
      incoming            True for senators taking a seat in the new Congress
      has_voting_record   True if any DW-NOMINATE score exists (House or Senate)
      new_to_senate       True for incoming senators with no prior Senate service;
                          a returning former senator is incoming but not new
    """
    if roster["bioguide_id"].duplicated().any():
        dupes = roster.loc[roster["bioguide_id"].duplicated(), "bioguide_id"].tolist()
        raise ValueError(f"Duplicate Bioguide IDs in roster: {dupes}")

    roster = roster.copy()
    roster["state"] = roster["state"].map(config.state_code)
    merged = roster.merge(voteview, on="bioguide_id", how="left", validate="one_to_one")
    merged = assign_caucus(merged)

    if "incoming" not in merged:
        merged["incoming"] = False
    merged["incoming"] = merged["incoming"].astype("boolean").fillna(False).astype(bool)
    if "senate_congresses_served" not in merged:
        merged["senate_congresses_served"] = 0
    merged["senate_congresses_served"] = merged["senate_congresses_served"].fillna(0).astype(int)
    merged["has_voting_record"] = merged["nominate_dim1"].notna()
    # Either source showing prior Senate service is enough to rule out "new".
    prior_days = merged["prior_senate_days"].fillna(0) if "prior_senate_days" in merged else 0
    merged["new_to_senate"] = (
        merged["incoming"] & (merged["senate_congresses_served"] == 0) & (prior_days == 0)
    )
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

    sitting_without_score = df[~df["incoming"] & ~df["has_voting_record"]]
    if not sitting_without_score.empty:
        # A sitting senator should always have a score; a gap usually means an ID mismatch.
        print(
            "warning: sitting senators with no Voteview score (check Bioguide IDs): "
            f"{sitting_without_score['bioguide_id'].tolist()}"
        )

    incoming = df[df["incoming"]]
    if len(incoming):
        print(
            f"incoming: {len(incoming)} senators, {int(incoming['new_to_senate'].sum())} new to "
            f"the Senate, {int((~incoming['has_voting_record']).sum())} with no voting record."
        )
