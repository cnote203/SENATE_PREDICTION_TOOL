"""Offline tests for the shared scoring engine and the foreign policy module."""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim.policy import base, foreign_policy  # noqa: E402

FP = foreign_policy.MODULE


def baseline():
    """Small roster: two sitting Democrats, two sitting Republicans, a House-scored
    Republican, and two Democrats with no record (one in a split state)."""
    rows = [
        ("D1", "Lib", "MA", "D", -0.50, 0.10, "Senate"),
        ("D2", "Mod", "MA", "D", -0.30, 0.00, "Senate"),
        ("R1", "Con", "WY", "R", 0.60, 0.20, "Senate"),
        ("R2", "CR", "TX", "R", 0.40, 0.00, "Senate"),
        ("R3", "Rep", "WY", "R", 0.70, 0.10, "House"),
        ("N1", "NewSafe", "VT", "D", None, None, None),
        ("N2", "NewRed", "TX", "D", None, None, None),
    ]
    return pd.DataFrame(rows, columns=["bioguide_id", "name", "state", "caucus",
                                       "nominate_dim1", "nominate_dim2", "score_chamber"])


def module_with(overrides: str | None):
    tmp = Path(tempfile.mkdtemp()) / "ov.csv"
    if overrides is not None:
        tmp.write_text(overrides)
    return replace(FP, override_path=tmp)


HEADER = "bioguide_id,name,dimension,score,sd,evidence,roll_calls,verified\n"


class Imputation(unittest.TestCase):
    def setUp(self):
        self.ideo = base.impute_ideology(baseline()).set_index("bioguide_id")

    def test_record_holders_keep_their_point(self):
        self.assertAlmostEqual(self.ideo.loc["D1", "dim1"], -0.50)
        self.assertEqual(self.ideo.loc["R3", "ideology_source"], "House")

    def test_no_record_gets_caucus_median(self):
        self.assertAlmostEqual(self.ideo.loc["N1", "dim1"], -0.40)  # median of -0.5, -0.3
        self.assertEqual(self.ideo.loc["N1", "dim2"], 0.0)
        self.assertEqual(self.ideo.loc["N1", "ideology_source"], "imputed")

    def test_split_state_pulls_toward_centre(self):
        expected = -0.40 * (1 - base.CROSS_PRESSURE_SHIFT)
        self.assertAlmostEqual(self.ideo.loc["N2", "dim1"], expected)


class ForeignPolicyFormulas(unittest.TestCase):
    def f(self, name, d1, d2=0.0):
        dim = next(d for d in FP.dimensions if d.name == name)
        return float(dim.formula(np.array([d1]), np.array([d2]))[0])

    def test_defense_and_china_rise_with_conservatism(self):
        self.assertLess(self.f("defense_budget", -0.4), self.f("defense_budget", 0.5))
        self.assertLess(self.f("china_decoupling", -0.4), self.f("china_decoupling", 0.5))

    def test_interventionism_peaks_near_centre(self):
        centre = self.f("nato_interventionism", 0.1)
        self.assertGreater(centre, self.f("nato_interventionism", -0.6))
        self.assertGreater(centre, self.f("nato_interventionism", 0.9))

    def test_arms_oversight_highest_on_left(self):
        self.assertGreater(self.f("arms_sales_oversight", -0.6), self.f("arms_sales_oversight", 0.4))

    def test_four_dimensions_defined_with_labels(self):
        self.assertEqual(FP.dimension_names, ["nato_interventionism", "defense_budget",
                                              "arms_sales_oversight", "china_decoupling"])
        for d in FP.dimensions:
            self.assertTrue(d.low and d.high)


class Engine(unittest.TestCase):
    def test_scores_clamped_and_uncertainty_by_source(self):
        mod = module_with(None)
        df = base.score(baseline(), mod).set_index("bioguide_id")
        for d in mod.dimension_names:
            self.assertTrue(df[d].between(-2, 2).all())
        self.assertEqual(df.loc["D1", "defense_budget_sd"], base.SD_BY_SOURCE["Senate"])
        self.assertEqual(df.loc["R3", "defense_budget_sd"], base.SD_BY_SOURCE["House"])
        self.assertEqual(df.loc["N1", "defense_budget_sd"], base.SD_BY_SOURCE["imputed"])
        self.assertEqual(df.loc["N1", "defense_budget_source"], "imputed")

    def test_extreme_point_is_clamped(self):
        b = baseline()
        b.loc[0, "nominate_dim1"] = -5.0
        df = base.score(b, module_with(None)).set_index("bioguide_id")
        self.assertEqual(df.loc["D1", "defense_budget"], -2.0)

    def test_override_replaces_score_and_sd(self):
        mod = module_with(HEADER + "R1,Con,nato_interventionism,-2,0.2,test,,no\n")
        df = base.score(baseline(), mod).set_index("bioguide_id")
        self.assertEqual(df.loc["R1", "nato_interventionism"], -2.0)
        self.assertEqual(df.loc["R1", "nato_interventionism_sd"], 0.2)
        self.assertEqual(df.loc["R1", "nato_interventionism_source"], "override")
        self.assertEqual(df.loc["R1", "defense_budget_source"], "formula")

    def test_override_validation(self):
        bad = {
            "unknown id": "ZZZ,X,defense_budget,1,0.2,e,,no\n",
            "unknown dimension": "R1,X,healthcare,1,0.2,e,,no\n",
            "out of range": "R1,X,defense_budget,3,0.2,e,,no\n",
            "duplicate": "R1,X,defense_budget,1,0.2,e,,no\nR1,X,defense_budget,0,0.2,e,,no\n",
        }
        for label, rows in bad.items():
            with self.subTest(label), self.assertRaises(ValueError):
                base.score(baseline(), module_with(HEADER + rows))

    def test_seeded_override_file_is_well_formed(self):
        ov = pd.read_csv(FP.override_path)
        self.assertEqual(list(ov.columns), base.OVERRIDE_COLUMNS)
        self.assertTrue(ov["dimension"].isin(FP.dimension_names).all())
        self.assertTrue(ov["score"].between(-2, 2).all())
        self.assertFalse(ov.duplicated(["bioguide_id", "dimension"]).any())


if __name__ == "__main__":
    unittest.main()
