"""Offline tests for election draws and the multi-cycle simulation."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import elections, multicycle  # noqa: E402
from senate_sim.policy import foreign_policy  # noqa: E402
from senate_sim.simulation import PRESETS  # noqa: E402

STATES = sorted(elections.ELECTORAL_VOTES)[:50]


def lean():
    rng = np.random.default_rng(0)
    return {s: float(v) for s, v in zip(elections.ELECTORAL_VOTES, rng.normal(0, 15, 51))}


class Elections(unittest.TestCase):
    def test_ev_total(self):
        self.assertEqual(sum(elections.ELECTORAL_VOTES.values()), 538)

    def test_state_lean_from_counties(self):
        csv = (b"state_name,county_fips,county_name,votes_gop,votes_dem,total_votes\n"
               b"Vermont,1,A,30,70,100\nWyoming,2,B,70,30,100\nWyoming,3,C,70,30,100\n")
        out = elections.state_lean(csv).set_index("state")
        self.assertAlmostEqual(out.loc["VT", "margin"], 40.0)
        self.assertAlmostEqual(out.loc["WY", "margin"], -40.0)
        national = (70 + 60 - 30 - 140) / 300 * 100
        self.assertAlmostEqual(out.loc["VT", "lean"], 40.0 - national)

    def test_environment_recovered_from_winners(self):
        rng = np.random.default_rng(1)
        l = lean()
        rows = []
        for _ in range(8):
            for s in list(l)[:50]:
                inc = rng.choice(["D", "R", None])
                m = elections.race_mean(np.array([l[s]]), 6.0, np.array([inc or ""]))[0]
                win = "D" if m + rng.normal(0, elections.RACE_SD) > 0 else "R"
                rows.append({"state": s, "winner": win, "incumbent_party": inc})
        env, se = elections.estimate_environment(pd.DataFrame(rows), l)
        self.assertAlmostEqual(env, 6.0, delta=2.5)
        self.assertGreater(se, 0)

    def test_president_conditioning(self):
        rng = np.random.default_rng(2)
        for want in ("D", "R"):
            winner, national, ev = elections.draw_president(rng, 0.0, lean(), want)
            self.assertEqual(winner, want)
            self.assertEqual(winner == "D", ev >= 270)

    def test_retirement_rises_with_age(self):
        self.assertLess(elections.retire_prob(55), elections.retire_prob(72))
        self.assertLess(elections.retire_prob(72), elections.retire_prob(85))


def roster(n_d=56):
    rows = []
    states = [s for s in elections.ELECTORAL_VOTES if s != "DC"]
    for i, s in enumerate(states):
        for k in range(2):
            idx = 2 * i + k
            cls = [1, 2, 3][idx % 3]
            caucus = "D" if idx < n_d else "R"
            rows.append({"bioguide_id": f"B{idx:03d}", "name": f"Sen {idx}", "state": s, "caucus": caucus,
                         "senate_class": cls, "nominate_dim1": -0.4 if caucus == "D" else 0.5,
                         "nominate_dim2": 0.0, "score_chamber": "Senate", "incoming": False})
    return pd.DataFrame(rows)


class Mechanics(unittest.TestCase):
    def test_control_uses_vice_president_on_ties(self):
        r = roster(50)
        self.assertEqual(multicycle.control(r, "D"), "D")
        self.assertEqual(multicycle.control(r, "R"), "R")
        self.assertEqual(multicycle.control(roster(51), "R"), "D")

    def test_only_the_class_up_changes(self):
        rng = np.random.default_rng(3)
        r = roster().assign(birth_year=1960)
        out = multicycle.hold_elections(rng, r, 3, 2028, env=-30.0, lean={s: 0.0 for s in r["state"]})
        unchanged = out[out["senate_class"] != 3].set_index("bioguide_id")
        self.assertEqual(len(unchanged), (r["senate_class"] != 3).sum())
        self.assertFalse(unchanged["incoming"].any())
        class3 = out[out["senate_class"] == 3]
        # A D-30 environment flips nearly every Democratic Class 3 seat.
        self.assertGreater((class3["caucus"] == "R").mean(), 0.9)
        self.assertTrue(class3[class3["incoming"]]["bioguide_id"].str.startswith("SIM2028").all())

    def test_fill_vacancies_respects_caucus_and_limits(self):
        rng = np.random.default_rng(4)
        r = roster()
        a = pd.DataFrame([
            {"committee_id": "SSFR", "committee_name": "FR", "tier": "Super A", "side": "majority",
             "bioguide_id": None, "member_name": None, "caucus": "D", "side_rank": 1, "status": "vacancy", "title": ""},
            {"committee_id": "SSFR", "committee_name": "FR", "tier": "Super A", "side": "minority",
             "bioguide_id": None, "member_name": None, "caucus": None, "side_rank": 1, "status": "vacancy", "title": ""},
        ])
        out = multicycle.fill_vacancies(rng, a, r, "D").set_index("side")
        cau = r.set_index("bioguide_id")["caucus"]
        self.assertEqual(cau[out.loc["majority", "bioguide_id"]], "D")
        self.assertEqual(cau[out.loc["minority", "bioguide_id"]], "R")
        self.assertTrue((out["status"] == "member").all())


class EndToEnd(unittest.TestCase):
    def test_small_run(self):
        r = roster()
        seats = []
        for side, cau in (("majority", "D"), ("minority", "R")):
            members = r[r["caucus"] == cau]["bioguide_id"].tolist()[:5]
            for k, b in enumerate(members, start=1):
                seats.append({"committee_id": "SSFR", "committee_name": "Foreign Relations", "tier": "Super A",
                              "side": side, "bioguide_id": b, "member_name": b, "caucus": cau,
                              "side_rank": k, "status": "member", "title": ""})
        assignments = pd.DataFrame(seats)
        mod = replace(foreign_policy.MODULE, override_path=Path("/nonexistent.csv"))
        l = {s: 0.0 for s in r["state"]}
        scen = multicycle.Scenario(president_2028="R", runs=3, inner_runs=50, seed=5)
        res = multicycle.run(r, {}, l, assignments, mod, None,
                             {"ndaa_passage": PRESETS["ndaa_passage"]}, scen)
        s = multicycle.summarize(res)
        self.assertEqual(sorted(s["congress"]["congress"]), [120, 121, 122])
        self.assertTrue((res["congress"].query("congress > 120")["president"] == "R").all())
        self.assertEqual(len(res["measures"]), 3 * 3)
        self.assertIn("SSFR_chair", res["leadership"].columns)


if __name__ == "__main__":
    unittest.main()
