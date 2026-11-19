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
    # Sitting senator with a long Senate record.
    "118,Senate,1,VT,328,SANDERS,S000033,-0.50,0.1,600\n"
    "119,Senate,1,VT,328,SANDERS,S000033,-0.52,0.1,500\n"
    # House member moving to the Senate: latest score is from the House.
    "118,House,2,AL,200,MOORE,M001212,0.70,0.2,900\n"
    "119,House,2,AL,200,MOORE,M001212,0.72,0.2,800\n"
    # Former senator returning after a gap, with earlier House service.
    "109,House,3,OH,100,BROWN,B000944,-0.40,0.0,900\n"
    "110,Senate,3,OH,100,BROWN,B000944,-0.44,0.0,600\n"
    "118,Senate,3,OH,100,BROWN,B000944,-0.45,0.0,550\n"
    # Data after the cutoff must be ignored.
    "120,Senate,1,VT,328,SANDERS,S000033,0.99,0.9,10\n"
    # Rows to skip: presidents and missing IDs.
    "119,President,9,USA,200,PRESIDENT,P999999,0.50,0.0,0\n"
    "119,Senate,8,XX,200,NO ID,,0.30,0.0,100\n"
)


class VoteviewHistory(unittest.TestCase):
    def setUp(self):
        self.df = voteview.parse_all_members(VOTEVIEW_CSV.encode(), through_congress=119)
        self.by_id = self.df.set_index("bioguide_id")

    def test_one_row_per_member_and_presidents_dropped(self):
        self.assertEqual(self.df["bioguide_id"].duplicated().sum(), 0)
        self.assertNotIn("P999999", self.by_id.index)

    def test_latest_score_respects_cutoff(self):
        self.assertAlmostEqual(self.by_id.loc["S000033", "nominate_dim1"], -0.52)
        self.assertEqual(self.by_id.loc["S000033", "score_congress"], 119)

    def test_house_member_keeps_house_score(self):
        row = self.by_id.loc["M001212"]
        self.assertAlmostEqual(row["nominate_dim1"], 0.72)
        self.assertEqual(row["score_chamber"], "House")
        self.assertEqual(row["senate_congresses_served"], 0)

    def test_returning_senator_service_counted(self):
        row = self.by_id.loc["B000944"]
        self.assertEqual(row["senate_congresses_served"], 2)
        self.assertEqual(row["first_senate_congress"], 110)
        self.assertEqual(row["score_chamber"], "Senate")

    def test_missing_column_raises(self):
        bad = VOTEVIEW_CSV.replace("nominate_dim2", "nope").encode()
        with self.assertRaises(ValueError):
            voteview.parse_all_members(bad)


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
