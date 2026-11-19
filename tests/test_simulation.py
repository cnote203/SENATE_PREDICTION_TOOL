"""Offline tests for the Monte Carlo vote model and procedural gates."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import simulation as sim  # noqa: E402


def scores(d_score=1.0, r_score=-1.0, n_d=56, n_r=44, sd=0.3):
    return pd.DataFrame({
        "name": [f"D{i}" for i in range(n_d)] + [f"R{i}" for i in range(n_r)],
        "caucus": ["D"] * n_d + ["R"] * n_r,
        "arms_sales_oversight": [d_score] * n_d + [r_score] * n_r,
        "arms_sales_oversight_sd": [sd] * (n_d + n_r),
    })


def calib(gamma=0.0, identified=False, alpha=0.0):
    return {"arms_sales_oversight": {
        "beta": {"d1": -1.0, "d1_sq": 0.0, "d2": 0.0}, "gamma": gamma, "gamma_identified": identified,
        "scale": {"mean": 0.0, "sd": 1.35, "k": 0.9}, "sigma_score": 0.4,
        "items": [{"item_id": "a", "family": "israel_fms", "alpha": alpha},
                  {"item_id": "b", "family": "israel_fms", "alpha": alpha}],
    }}


MEASURE = sim.PRESETS["israel_arms_disapproval"]


class Thresholds(unittest.TestCase):
    def test_gates(self):
        y, n = np.array([51, 50, 60, 59, 66, 67]), np.array([49, 50, 40, 41, 34, 33])
        self.assertEqual(sim._passes(y, n, "majority", False).tolist(), [True, False, True, True, True, True])
        self.assertEqual(sim._passes(np.array([50]), np.array([50]), "majority", True).tolist(), [True])
        self.assertEqual(sim._passes(y, n, "cloture", False).tolist(), [False, False, True, False, True, True])
        self.assertEqual(sim._passes(np.array([66, 67]), np.array([34, 33]), "two_thirds", False).tolist(),
                         [False, True])

    def test_required_defectors(self):
        self.assertEqual(sim.required_defectors(44), 11)
        self.assertEqual(sim.required_defectors(56), 23)


class VoteModel(unittest.TestCase):
    def test_clear_majority_passes_senate_but_veto_blocks(self):
        r = sim.simulate(scores(d_score=2.0, r_score=-2.0), MEASURE, "R", calib(), runs=2000)
        self.assertGreater(r["p_passes_senate"], 0.95)
        self.assertLess(r["p_senate_override_if_passed"], 0.05)
        self.assertLess(r["p_enacted"], r["p_passes_both_chambers"])

    def test_copartisan_effect_changes_outcome_by_white_house(self):
        # Even caucuses, gamma pulls the President's party away from oversight.
        s = scores(d_score=0.0, r_score=0.0, n_d=50, n_r=50)
        cal = calib(gamma=-1.0, identified=True)
        under_r = sim.simulate(s, MEASURE, "R", cal, runs=3000)
        under_d = sim.simulate(s, MEASURE, "D", cal, runs=3000)
        # Same senators, symmetric parties: outcome is driven by tie rules and noise only.
        self.assertAlmostEqual(under_r["p_passes_senate"], under_d["p_passes_senate"], delta=0.1)
        # With Democrats more supportive, a Democratic White House cuts Democratic support.
        s2 = scores(d_score=0.5, r_score=-0.5, n_d=56, n_r=44)
        r_wh = sim.simulate(s2, MEASURE, "R", cal, runs=3000)["stages"]["passage"]["yeas_median"]
        d_wh = sim.simulate(s2, MEASURE, "D", cal, runs=3000)["stages"]["passage"]["yeas_median"]
        self.assertGreater(r_wh, d_wh)

    def test_nay_plus_side_inverts(self):
        m = replace(MEASURE, plus_side="Nay")
        r = sim.simulate(scores(), m, "R", calib(), runs=1000)
        self.assertLess(r["p_passes_senate"], 0.05)

    def test_uncalibrated_defaults_run(self):
        r = sim.simulate(scores(), MEASURE, "D", None, runs=500)
        self.assertFalse(r["parameters"]["calibrated"])
        self.assertIn("pivotal_senators", r)

    def test_cloture_stage(self):
        s = scores().rename(columns={"arms_sales_oversight": "defense_budget",
                                     "arms_sales_oversight_sd": "defense_budget_sd"})
        m = sim.PRESETS["ndaa_passage"]
        r = sim.simulate(s, m, "R", None, runs=1000)  # 56 supporters, under 60
        self.assertLess(r["stages"]["cloture"]["p_pass_cumulative"], 0.5)


if __name__ == "__main__":
    unittest.main()


class Drift(unittest.TestCase):
    def fam(self):
        return pd.DataFrame({
            "date": ["2025-04-03", "2025-04-03", "2025-07-30", "2025-07-30", "2026-04-15"],
            "alpha": [-2.0, -2.0, -1.4, -1.5, -0.6],
            "family": "israel_fms",
        })

    def test_latest_starts_at_most_recent_vote_and_widens(self):
        near = sim.latest_cutpoint(self.fam(), "2026-05-15")
        far = sim.latest_cutpoint(self.fam(), "2028-04-15")
        self.assertAlmostEqual(near["alpha"], -0.6)
        self.assertEqual(near["latest_date"], "2026-04-15")
        self.assertGreater(far["sd"], near["sd"])

    def test_too_few_dated_votes_falls_back(self):
        self.assertIsNone(sim.latest_cutpoint(self.fam().iloc[:2], "2027-01-01"))
        self.assertIsNone(sim.latest_cutpoint(self.fam().drop(columns="date"), "2027-01-01"))

    def test_latest_mode_moves_the_measure(self):
        cal = calib()
        cal["arms_sales_oversight"]["items"] = [
            {"item_id": str(i), "family": "israel_fms", "alpha": a, "date": d}
            for i, (d, a) in enumerate(zip(self.fam()["date"], self.fam()["alpha"]))
        ]
        s = scores(d_score=0.6, r_score=-1.5)
        latest = sim.simulate(s, MEASURE, "R", cal, runs=2000)
        family = sim.simulate(s, replace(MEASURE, alpha_mode="family"), "R", cal, runs=2000)
        self.assertGreater(latest["stages"]["passage"]["yeas_median"],
                           family["stages"]["passage"]["yeas_median"])
