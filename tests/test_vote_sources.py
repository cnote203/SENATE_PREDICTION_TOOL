"""Offline tests for the Voteview roll-call source."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim.ingest import vote_sources as vs  # noqa: E402

ROLLCALLS = pd.DataFrame({
    "congress": [119, 119, 119], "chamber": ["Senate", "Senate", "House"],
    "rollnumber": [166, 712, 166], "date": ["2025-04-03", "2026-04-15", "2025-04-03"],
    "session": [1, 2, 1], "clerk_rollnumber": [166, 80, 166],
    "yea_count": [15, 40, 200], "nay_count": [83, 59, 200],
    "vote_question": ["On the Motion to Discharge", "On the Motion to Discharge", "House"],
    "bill_number": ["SJRES26", "SJRES32", "HR1"],
})
VOTES = pd.DataFrame({
    "congress": 119, "chamber": "Senate",
    "rollnumber": [712, 712, 712, 712, 166],
    "icpsr": [29147, 41110, 41500, 99999, 29147],
    "cast_code": [1, 6, 9, 0, 1],
})
MEMBERS = pd.DataFrame({
    "congress": 119, "chamber": "Senate",
    "icpsr": [29147, 41110, 41500], "bioguide_id": ["S000033", "P000603", "L000571"],
    "party_code": [328, 200, 200],
})


class Voteview(unittest.TestCase):
    def setUp(self):
        self.prepared = vs.prepare_voteview(ROLLCALLS, VOTES, MEMBERS, 119)

    def test_clerk_number_within_session_maps_to_voteview_number(self):
        meta, votes = vs.select_voteview(*self.prepared, 119, 2, 80)
        self.assertEqual((meta["yeas"], meta["nays"]), (40, 59))
        v = votes.set_index("bioguide_id")
        self.assertEqual(v.loc["S000033", "yea"], 1.0)
        self.assertEqual(v.loc["S000033", "party"], "I")
        self.assertEqual(v.loc["P000603", "yea"], 0.0)
        self.assertTrue(np.isnan(v.loc["L000571", "yea"]))
        self.assertEqual(len(votes), 3)  # cast_code 0 (not a member) dropped

    def test_house_rows_ignored_and_missing_roll_raises(self):
        meta, votes = vs.select_voteview(*self.prepared, 119, 1, 166)
        self.assertEqual(meta["yeas"], 15)
        with self.assertRaises(LookupError):
            vs.select_voteview(*self.prepared, 119, 2, 999)

    def test_session_derived_from_date_when_absent(self):
        rc = ROLLCALLS.drop(columns="session")
        prepared = vs.prepare_voteview(rc, VOTES, MEMBERS, 119)
        meta, _ = vs.select_voteview(*prepared, 119, 2, 80)
        self.assertEqual(meta["roll"], 80)

    def test_first_year(self):
        self.assertEqual(vs.first_year(119), 2025)
        self.assertEqual(vs.first_year(118), 2023)


if __name__ == "__main__":
    unittest.main()
