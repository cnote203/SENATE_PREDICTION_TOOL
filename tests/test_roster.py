"""Offline tests for the ingestion parsers and roster merge.

Run with:  python -m unittest discover -s tests -v
No network access or API keys are needed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import config  # noqa: E402
from senate_sim.ingest import congress_gov, voteview  # noqa: E402
from senate_sim.roster import assign_caucus, build_baseline, validate_baseline  # noqa: E402


def _synthetic_roster(d: int = 54, i_caucus_d: int = 2, r: int = 44) -> pd.DataFrame:
    """Build a 100-seat roster with the expected split. Sanders and King are the caucusing independents."""
    rows = []
    caucus_ids = list(config.CAUCUS_WITH_DEMOCRATS)
    for n in range(d):
        rows.append({"bioguide_id": f"D{n:04d}", "name": f"Dem {n}", "state": "XX",
                     "api_party": "Democratic"})
    for bid in caucus_ids[:i_caucus_d]:
        rows.append({"bioguide_id": bid, "name": bid, "state": "XX", "api_party": "Independent"})
    for n in range(r):
        rows.append({"bioguide_id": f"R{n:04d}", "name": f"Rep {n}", "state": "XX",
                     "api_party": "Republican"})
    return pd.DataFrame(rows)


def _synthetic_voteview(ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bioguide_id": ids,
            "icpsr": range(len(ids)),
            "vv_state": "XX",
            "vv_party": "Democrat",
            "nominate_dim1": [0.1] * len(ids),
            "nominate_dim2": [0.0] * len(ids),
            "nominate_votes": [100] * len(ids),
        }
    )


VOTEVIEW_CSV = (
    "congress,chamber,icpsr,state_abbrev,party_code,bioname,bioguide_id,"
    "nominate_dim1,nominate_dim2,nominate_number_of_votes\n"
    "119,Sen,1,VT,328,SANDERS,S000033,-0.4,0.1,500\n"
    "119,Sen,2,XX,200,OLD SEAT,X000001,0.5,0.0,10\n"
    "119,Sen,3,XX,200,OLD SEAT REPLACEMENT,X000001,0.5,0.0,300\n"
    "119,House,4,XX,200,HOUSE MEMBER,H000001,0.2,0.2,400\n"
    "118,Sen,5,XX,100,PRIOR CONGRESS,P000001,0.0,0.0,900\n"
)


class VoteviewParsing(unittest.TestCase):
    def test_keeps_senate_members_for_requested_congress_only(self):
        df = voteview.parse_members_csv(VOTEVIEW_CSV.encode(), congress=119)
        self.assertNotIn("H000001", df["bioguide_id"].tolist())
        self.assertNotIn("P000001", df["bioguide_id"].tolist())

    def test_dedupes_replacement_seat_keeping_most_votes(self):
        df = voteview.parse_members_csv(VOTEVIEW_CSV.encode(), congress=119)
        row = df[df["bioguide_id"] == "X000001"].iloc[0]
        self.assertEqual(row["nominate_votes"], 300)
        self.assertEqual(df["bioguide_id"].duplicated().sum(), 0)

    def test_maps_party_codes(self):
        df = voteview.parse_members_csv(VOTEVIEW_CSV.encode(), congress=119)
        self.assertEqual(df.set_index("bioguide_id").loc["S000033", "vv_party"], "Independent")

    def test_missing_column_raises(self):
        bad = VOTEVIEW_CSV.replace("nominate_dim2", "nope").encode()
        with self.assertRaises(ValueError):
            voteview.parse_members_csv(bad, congress=119)


class CongressGovParsing(unittest.TestCase):
    def test_filters_to_senate_terms_in_congress(self):
        members = [
            {"bioguideId": "A000001", "name": "Ada", "state": "Maine", "partyName": "Democratic",
             "terms": {"item": [{"chamber": "Senate", "congress": 120}]}},
            {"bioguideId": "B000002", "name": "Bo", "state": "Ohio", "partyName": "Republican",
             "terms": {"item": [{"chamber": "House of Representatives", "congress": 120}]}},
            {"bioguideId": "C000003", "name": "Cy", "state": "Iowa", "partyName": "Republican",
             "terms": {"item": [{"chamber": "Senate", "congress": 119}]}},
        ]
        df = congress_gov.parse_members_payload(members, congress=120)
        self.assertEqual(df["bioguide_id"].tolist(), ["A000001"])

    def test_handles_terms_as_plain_list(self):
        members = [{"bioguideId": "A000001", "name": "Ada", "state": "Maine",
                    "partyName": "Democratic",
                    "terms": [{"chamber": "Senate", "congress": 120}]}]
        df = congress_gov.parse_members_payload(members, congress=120)
        self.assertEqual(len(df), 1)


class CaucusAndBaseline(unittest.TestCase):
    def test_independents_on_caucus_list_count_as_democrats(self):
        roster = assign_caucus(_synthetic_roster())
        sanders = roster[roster["bioguide_id"] == "S000033"].iloc[0]
        self.assertEqual(sanders["caucus"], "D")
        self.assertEqual(sanders["api_party"], "Independent")

    def test_unknown_independent_stays_independent(self):
        df = pd.DataFrame([{"bioguide_id": "Z000009", "api_party": "Independent"}])
        self.assertEqual(assign_caucus(df).iloc[0]["caucus"], "I")

    def test_expected_split_passes_validation(self):
        roster = _synthetic_roster()
        ids = roster["bioguide_id"].tolist()
        baseline = build_baseline(roster, _synthetic_voteview(ids))
        validate_baseline(baseline)  # no exception

    def test_wrong_split_fails_validation(self):
        roster = _synthetic_roster(d=54, i_caucus_d=1, r=45)  # 100 seats, but split is 55 D / 45 R
        ids = roster["bioguide_id"].tolist()
        baseline = build_baseline(roster, _synthetic_voteview(ids))
        with self.assertRaises(ValueError):
            validate_baseline(baseline)

    def test_duplicate_bioguide_rejected(self):
        roster = _synthetic_roster()
        roster = pd.concat([roster, roster.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            build_baseline(roster, _synthetic_voteview(roster["bioguide_id"].unique().tolist()))


if __name__ == "__main__":
    unittest.main()
