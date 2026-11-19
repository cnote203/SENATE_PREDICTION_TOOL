"""Central configuration for the Senate policy simulation.

Values that are assumptions rather than facts are marked AUDIT so they can be
checked before any results are trusted.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# The 120th Congress convenes January 3, 2027.
ROSTER_CONGRESS = 120
# Latest Congress whose Voteview data the baseline may use (DW-NOMINATE).
# AUDIT: raise to 120 once Voteview publishes that Congress.
VOTEVIEW_CONGRESS = 119

CONGRESS_API_BASE = "https://api.congress.gov/v3"
VOTEVIEW_ALL_MEMBERS_URL = "https://voteview.com/static/data/out/members/HSall_members.csv"

# API keys come from the environment and are never written to disk or logged.
CONGRESS_API_KEY_ENV = "CONGRESS_API_KEY"
OPENFEC_API_KEY_ENV = "OPENFEC_API_KEY"

# Contact string sent in the User-Agent header, as good API etiquette.
CONTACT_ENV = "SENATE_SIM_CONTACT"

# Independents who caucus with the Democrats, keyed by Bioguide ID.
# AUDIT: verify these IDs against Congress.gov before relying on them.
CAUCUS_WITH_DEMOCRATS = {
    "K000383": "King (I-ME)",
    "S000033": "Sanders (I-VT)",
}

# Expected Senate split for the 120th Congress, used as a validation gate.
# Source: AP results for the Nov 3, 2026 general election, as of
# Nov 19, 2026, 2:01 p.m. ET. Totals include the two caucusing independents
# in the Democratic count. AUDIT: update if AP's count changes.
EXPECTED_SPLIT = {"D": 56, "R": 44}
EXPECTED_TOTAL = 100


def congress_api_key() -> str:
    key = os.environ.get(CONGRESS_API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"Set {CONGRESS_API_KEY_ENV} to a Congress.gov API key "
            "(free key from api.data.gov)."
        )
    return key


def user_agent() -> str:
    contact = os.environ.get(CONTACT_ENV, "unset")
    return f"senate-sim/0.1 (contact: {contact})"

# Full state names (as Congress.gov returns them) to postal codes.
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
    "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def state_code(value: str) -> str:
    """Return the postal code for a state given as a full name or a code."""
    value = str(value or "").strip()
    if value.upper() in STATE_CODES.values():
        return value.upper()
    return STATE_CODES.get(value, value)
