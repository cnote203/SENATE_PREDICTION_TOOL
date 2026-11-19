"""Project the next Congress's roster from the current one plus known seat changes.

Used until Congress.gov publishes the new Congress (it convenes January 3).
The changes file is hand-maintained: one row per seat where the senator
changes, whether by defeat, retirement, or appointment.

File: data/manual/seat_changes_2026.csv
Columns:
    state              two-letter postal code of the seat
    outgoing_bioguide  Bioguide ID of the senator leaving
    incoming_name      name of the senator taking the seat
    incoming_party     Democratic, Republican, or Independent
    incoming_bioguide  Bioguide ID if the incoming senator has one (former
                       House members do); leave blank otherwise
    caucus_with_d      'yes' for an independent who caucuses with Democrats
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from senate_sim import config

SEAT_CHANGES_PATH = config.PROJECT_ROOT / "data" / "manual" / "seat_changes_2026.csv"
COLUMNS = [
    "state",
    "outgoing_bioguide",
    "incoming_name",
    "incoming_party",
    "incoming_bioguide",
    "caucus_with_d",
]


def load_seat_changes(path: Path = SEAT_CHANGES_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Seat changes file not found: {path}")
    df = pd.read_csv(path, dtype=str).fillna("")
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
    return df


def apply_seat_changes(current: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """Swap outgoing senators for incoming ones and return the projected roster.

    A change is skipped when the swap has already happened in the source data
    (outgoing senator gone, incoming senator present), which covers special-election
    winners sworn in before January 3 and every row once the new Congress convenes.
    Incoming senators without a Bioguide ID get a placeholder like NEW-MI-1.
    The incoming senator inherits the seat's Senate class from the outgoing one.
    """
    if changes["outgoing_bioguide"].duplicated().any():
        raise ValueError("A senator appears more than once as outgoing.")

    ids = set(current["bioguide_id"])
    pending = changes["outgoing_bioguide"].isin(ids)
    done = ~pending & changes["incoming_bioguide"].str.strip().isin(ids) & (changes["incoming_bioguide"].str.strip() != "")
    broken = ~pending & ~done
    if broken.any():
        raise ValueError(
            "Outgoing Bioguide IDs not in the current roster (and the incoming senator "
            f"is not there either): {sorted(changes.loc[broken, 'outgoing_bioguide'])}"
        )

    current = current.copy()
    current["incoming"] = current["bioguide_id"].isin(changes.loc[done, "incoming_bioguide"].str.strip())
    outgoing = current.set_index("bioguide_id")
    kept = current[~current["bioguide_id"].isin(changes.loc[pending, "outgoing_bioguide"])]

    incoming = []
    placeholder_count: dict[str, int] = {}
    for _, row in changes[pending].iterrows():
        bid = row["incoming_bioguide"].strip()
        state = row["state"].strip().upper()
        if not bid:
            placeholder_count[state] = placeholder_count.get(state, 0) + 1
            bid = f"NEW-{state}-{placeholder_count[state]}"
        out_row = outgoing.loc[row["outgoing_bioguide"]]
        incoming.append(
            {
                "bioguide_id": bid,
                "name": row["incoming_name"].strip(),
                "state": row["state"].strip(),
                "api_party": row["incoming_party"].strip(),
                "caucus_with_d": row["caucus_with_d"].strip().lower() == "yes",
                "senate_class": out_row["senate_class"] if "senate_class" in outgoing else None,
                "incoming": True,
            }
        )

    projected = pd.concat([kept, pd.DataFrame(incoming)], ignore_index=True)
    for col in ("caucus_with_d", "incoming"):
        if col in projected:
            projected[col] = projected[col].astype("boolean").fillna(False).astype(bool)
    return projected
