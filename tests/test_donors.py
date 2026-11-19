"""Offline tests for OpenFEC parsing and the donor-effect analysis (mocked API)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import donors  # noqa: E402
from senate_sim.ingest import openfec  # noqa: E402


def fake_api(routes: dict):
    """routes: path -> list of pages (each a list of results)."""
    calls = []

    def get(path, params):
        calls.append((path, params))
        pages = routes.get(path, [[]])
        page = params.get("page", 1)
        return {"results": pages[page - 1] if page <= len(pages) else [],
                "pagination": {"pages": len(pages), "page": page}}
    return get, calls


class Resolve(unittest.TestCase):
    def test_keeps_matching_pacs_and_flags_leadership_or_stale(self):
        get, _ = fake_api({"/committees/": [[
            {"committee_id": "C1", "name": "LOCKHEED MARTIN CORPORATION EMPLOYEES' PAC",
             "committee_type": "Q", "designation": "B", "cycles": [2022, 2024, 2026]},
            {"committee_id": "C2", "name": "SOMETHING ELSE PAC", "committee_type": "Q",
             "designation": "U", "cycles": [2024]},
            {"committee_id": "C3", "name": "LOCKHEED MARTIN OLD PAC", "committee_type": "Q",
             "designation": "U", "cycles": [2010]},
        ]]})
        cats = pd.DataFrame([{"category": "defense_contractor", "search": "lockheed martin",
                              "pattern": "LOCKHEED MARTIN", "note": ""}])
        out = openfec.resolve_pacs(get, cats).set_index("committee_id")
        self.assertEqual(sorted(out.index), ["C1", "C3"])
        self.assertEqual(out.loc["C1", "include"], "yes")
        self.assertEqual(out.loc["C3", "include"], "no")


class Totals(unittest.TestCase):
    def test_pages_through_recipients_and_sums_per_senator(self):
        get, calls = fake_api({
            "/schedules/schedule_b/by_recipient_id/": [
                [{"recipient_id": "CAMP_A", "total": 5000}, {"recipient_id": "OTHER", "total": 100}],
                [{"recipient_id": "CAMP_B", "total": 2500}],
            ],
        })
        pacs = pd.DataFrame([{"category": "defense_contractor", "committee_id": "C1", "include": "yes"},
                             {"category": "defense_contractor", "committee_id": "C9", "include": "no"}])
        gifts = openfec.pac_to_recipients(get, pacs, cycles=[2024])
        self.assertEqual(len(gifts), 3)
        self.assertTrue(all(p["committee_id"] == "C1" for _, p in calls))
        committees = pd.DataFrame({"bioguide_id": ["S1", "S1"], "committee_id": ["CAMP_A", "CAMP_B"]})
        t = openfec.senator_totals(gifts, committees).set_index("bioguide_id")
        self.assertEqual(t.loc["S1", "fec_defense_contractor"], 7500)
        self.assertEqual(t.loc["S1", "npacs_defense_contractor"], 1)

    def test_senator_committees_falls_back_to_name_search(self):
        get, calls = fake_api({
            "/candidates/search/": [[{"candidate_id": "S6MI00001"}]],
            "/candidate/S6MI00001/committees/": [[{"committee_id": "CAMP_NEW"}]],
            "/candidate/S8XX00002/committees/": [[{"committee_id": "CAMP_OLD"}]],
        })
        roster = pd.DataFrame([
            {"bioguide_id": "NEW-MI-1", "name": "Abdul El-Sayed", "state": "MI", "fec_ids": ""},
            {"bioguide_id": "X1", "name": "Sitting", "state": "XX", "fec_ids": "S8XX00002"},
        ])
        out = openfec.senator_committees(get, roster).set_index("bioguide_id")
        self.assertEqual(out.loc["NEW-MI-1", "committee_id"], "CAMP_NEW")
        self.assertEqual(out.loc["NEW-MI-1", "resolved_by"], "name_search")
        self.assertEqual(out.loc["X1", "committee_id"], "CAMP_OLD")


class Effects(unittest.TestCase):
    def test_detects_a_real_within_caucus_relationship(self):
        rng = np.random.default_rng(0)
        n = 80
        ids = [f"S{i}" for i in range(n)]
        caucus = ["D"] * 40 + ["R"] * 40
        dollars = rng.lognormal(10, 1.2, n)
        # Deviation rises with log dollars inside each caucus, plus a caucus offset.
        u = 0.3 * np.log1p(dollars) + np.where(np.array(caucus) == "R", 1.0, 0.0) + rng.normal(0, 0.3, n)
        donors_df = pd.DataFrame({"bioguide_id": ids, "fec_defense_contractor": dollars})
        dev = pd.DataFrame({"bioguide_id": ids, "dimension": "defense_budget", "u_raw_score": u})
        out = donors.test_donor_effects(donors_df, dev, pd.DataFrame({"bioguide_id": ids, "caucus": caucus}))
        row = out[out["dimension"] == "defense_budget"].iloc[0]
        self.assertTrue(row["supports_hypothesis"])
        self.assertAlmostEqual(row["slope_per_log_dollar"], 0.3, delta=0.1)

    def test_caucus_gap_alone_is_not_an_effect(self):
        ids = [f"S{i}" for i in range(40)]
        caucus = ["D"] * 20 + ["R"] * 20
        rng = np.random.default_rng(1)
        dollars = np.where(np.array(caucus) == "R", 1e5, 1e3) * rng.uniform(0.9, 1.1, 40)
        u = np.where(np.array(caucus) == "R", 1.0, -1.0) + rng.normal(0, 0.3, 40)
        out = donors.test_donor_effects(
            pd.DataFrame({"bioguide_id": ids, "fec_defense_contractor": dollars}),
            pd.DataFrame({"bioguide_id": ids, "dimension": "defense_budget", "u_raw_score": u}),
            pd.DataFrame({"bioguide_id": ids, "caucus": caucus}))
        self.assertFalse(out.iloc[0]["supports_hypothesis"])


if __name__ == "__main__":
    unittest.main()
