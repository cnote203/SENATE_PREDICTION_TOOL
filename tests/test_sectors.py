"""Offline tests for the sector registry, bill lookup and per-White-House positions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import policy, simulation  # noqa: E402
from senate_sim.ingest import vote_sources as vs  # noqa: E402
from senate_sim.policy import base  # noqa: E402


def roster(n=100):
    rng = np.random.default_rng(0)
    caucus = np.array(["D"] * 56 + ["R"] * 44)
    d1 = np.where(caucus == "D", rng.normal(-0.35, 0.15, n), rng.normal(0.5, 0.15, n))
    ids = [f"S{i:03d}" for i in range(n)]
    ids[0], ids[1], ids[2] = "H001089", "B001277", "W000817"  # senators with tech overrides
    return pd.DataFrame({"bioguide_id": ids, "name": ids, "state": "XX", "caucus": caucus,
                         "nominate_dim1": d1, "nominate_dim2": rng.normal(0, 0.3, n),
                         "score_chamber": "Senate"})


class Registry(unittest.TestCase):
    def test_all_sectors_score_and_measures_point_at_real_dimensions(self):
        r = roster()
        for m in policy.all_modules():
            with self.subTest(m.name):
                s = base.score(r, m, None, strict_overrides=False)
                for d in m.dimension_names:
                    self.assertTrue(s[d].between(-2, 2).all())
                    self.assertTrue((s[f"{d}_sd"] > 0).all())
                for key, meas in m.measures.items():
                    self.assertIn(meas.dimension, m.dimension_names, key)
                self.assertTrue(m.label and m.committees)
                for d in m.dimensions:
                    self.assertTrue(d.label and d.short and d.low_tag and d.high_tag, d.name)

    def test_dimension_names_unique_across_sectors(self):
        names = [d for m in policy.all_modules() for d in m.dimension_names]
        self.assertEqual(len(names), len(set(names)))

    def test_tech_overrides_apply(self):
        s = base.score(roster(), policy.get("tech"), None, strict_overrides=False).set_index("bioguide_id")
        self.assertEqual(s.loc["W000817", "tech_antitrust"], 2.0)
        self.assertEqual(s.loc["W000817", "tech_antitrust_source"], "override")

    def test_presets_alias_still_works(self):
        from senate_sim.simulation import PRESETS
        self.assertIn("israel_arms_disapproval", PRESETS)


class Positions(unittest.TestCase):
    def test_position_by_white_house(self):
        m = policy.get("healthcare").measures["aca_credit_extension"]
        self.assertEqual(simulation.position_for(m, "R"), "oppose")
        self.assertEqual(simulation.position_for(m, "D"), "support")

    def test_veto_only_when_president_opposes(self):
        m = policy.get("healthcare").measures["aca_credit_extension"]
        s = base.score(roster(), policy.get("healthcare"), None, strict_overrides=False)
        under_r = simulation.simulate(s, m, "R", None, runs=300)
        under_d = simulation.simulate(s, m, "D", None, runs=300)
        self.assertIn("p_senate_override_if_passed", under_r)
        self.assertNotIn("p_senate_override_if_passed", under_d)


class BillLookup(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(vs.normalize_bill("S.J.Res. 18"), "SJRES18")
        self.assertEqual(vs.normalize_bill("hjres88"), "HJRES88")

    def test_find_by_bill_and_question(self):
        rc = pd.DataFrame({
            "bill_number": ["S1582", "S1582", "S1582", "HR1"],
            "vote_question": ["On Cloture on the Motion to Proceed", "On the Amendment", "On Passage of the Bill",
                              "On Passage of the Bill"],
            "session": [1, 1, 1, 1], "clerk_rollnumber": [240, 300, 318, 372],
            "date": ["2025-05-08", "2025-06-12", "2025-06-17", "2025-07-01"],
        })
        hits = vs.find_voteview(rc, "S.1582", "Cloture|Passage")
        self.assertEqual([h["roll"] for h in hits], [240, 318])
        self.assertEqual(vs.find_voteview(rc, "HR 1", "^On Passage")[0]["roll"], 372)
        self.assertEqual(vs.find_voteview(rc, "S9999", None), [])


if __name__ == "__main__":
    unittest.main()
