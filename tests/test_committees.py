"""Offline tests for congress-legislators parsing, seniority, and committee projection."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import committees  # noqa: E402
from senate_sim.ingest import legislators  # noqa: E402
from senate_sim.seat_changes import apply_seat_changes  # noqa: E402

AS_OF = date(2027, 1, 3)


def person(bid, terms, **ids):
    return {"id": {"bioguide": bid, **ids}, "name": {"official_full": bid}, "terms": terms}


def sen(start, end, **kw):
    return {"type": "sen", "start": start, "end": end, **kw}


def rep(start, end):
    return {"type": "rep", "start": start, "end": end}


class Service(unittest.TestCase):
    def test_continuous_terms_join(self):
        p = person("A", [sen("2015-01-06", "2021-01-03"), sen("2021-01-03", "2027-01-03")])
        s = legislators.service_summary(p, incoming=False, as_of=AS_OF)
        self.assertEqual(s["seniority_start"], "2015-01-06")
        self.assertEqual(s["prior_senate_days"], 0)

    def test_returning_senator_restarts_with_prior_credit(self):
        p = person("B", [rep("1993-01-05", "2007-01-03"), sen("2007-01-04", "2025-01-03")])
        s = legislators.service_summary(p, incoming=True, as_of=AS_OF)
        self.assertEqual(s["seniority_start"], "2027-01-03")
        self.assertGreater(s["prior_senate_days"], 6000)
        self.assertGreater(s["prior_house_days"], 5000)

    def test_unknown_incoming(self):
        s = legislators.service_summary(None, incoming=True, as_of=AS_OF)
        self.assertEqual((s["prior_senate_days"], s["prior_house_days"]), (0, 0))

    def test_rank_tiebreaks_on_prior_service(self):
        people = {
            "OLD": person("OLD", [sen("2001-01-03", "2027-01-03")]),
            "EXH": person("EXH", [rep("2011-01-05", "2027-01-03")]),
            "NEW": person("NEW", []),
        }
        df = pd.DataFrame({"bioguide_id": ["NEW", "EXH", "OLD"], "name": ["n", "e", "o"],
                           "incoming": [True, True, False]})
        out = legislators.add_service(df, people).set_index("bioguide_id")
        self.assertEqual(out.loc["OLD", "seniority_rank"], 1)
        self.assertEqual(out.loc["EXH", "seniority_rank"], 2)
        self.assertEqual(out.loc["NEW", "seniority_rank"], 3)

    def test_senators_from_current_keeps_appointees_and_caucus(self):
        current = [
            person("S1", [sen("2025-01-03", "2031-01-03", state="VT", party="Independent",
                              caucus="Democrat", **{"class": 1})], fec=["X1", "X2"]),
            person("H1", [rep("2025-01-03", "2027-01-03")]),
            person("AP", [sen("2025-01-21", "2026-11-03", state="OH", party="Republican",
                              how="appointment", **{"class": 3})]),
        ]
        df = legislators.senators_from_current(current).set_index("bioguide_id")
        self.assertEqual(sorted(df.index), ["AP", "S1"])
        self.assertEqual(df.loc["S1", "caucus_field"], "Democrat")
        self.assertEqual(df.loc["S1", "fec_ids"], "X1,X2")


class SeatChangesAlreadyApplied(unittest.TestCase):
    def test_swap_already_in_source_is_skipped(self):
        current = pd.DataFrame([
            {"bioguide_id": "NEWGUY", "name": "Winner", "state": "OH", "api_party": "Democrat", "senate_class": 3},
            {"bioguide_id": "STAY", "name": "Stay", "state": "OH", "api_party": "Republican", "senate_class": 1},
        ])
        changes = pd.DataFrame([{"state": "OH", "outgoing_bioguide": "GONE", "incoming_name": "Winner",
                                 "incoming_party": "Democratic", "incoming_bioguide": "NEWGUY",
                                 "caucus_with_d": ""}])
        out = apply_seat_changes(current, changes).set_index("bioguide_id")
        self.assertEqual(len(out), 2)
        self.assertTrue(out.loc["NEWGUY", "incoming"])
        self.assertFalse(out.loc["STAY", "incoming"])

    def test_incoming_inherits_seat_class(self):
        current = pd.DataFrame([{"bioguide_id": "OUT", "name": "Out", "state": "MI",
                                 "api_party": "Democrat", "senate_class": 2}])
        changes = pd.DataFrame([{"state": "MI", "outgoing_bioguide": "OUT", "incoming_name": "In",
                                 "incoming_party": "Democratic", "incoming_bioguide": "",
                                 "caucus_with_d": ""}])
        out = apply_seat_changes(current, changes)
        self.assertEqual(out.iloc[0]["senate_class"], 2)


class CommitteeProjection(unittest.TestCase):
    """A 9-seat Foreign Relations committee under a 5-4 Republican majority flips to Democrats."""

    def setUp(self):
        membership = {
            "SSFR": [
                {"bioguide": "R1", "name": "R1", "party": "majority", "rank": 1, "title": "Chairman"},
                {"bioguide": "R2", "name": "R2", "party": "majority", "rank": 2},
                {"bioguide": "R3", "name": "R3", "party": "majority", "rank": 3},
                {"bioguide": "R4", "name": "R4", "party": "majority", "rank": 4},
                {"bioguide": "R5", "name": "R5", "party": "majority", "rank": 5},
                {"bioguide": "D1", "name": "D1", "party": "minority", "rank": 1, "title": "Ranking Member"},
                {"bioguide": "D2", "name": "D2", "party": "minority", "rank": 2},
                {"bioguide": "D3", "name": "D3", "party": "minority", "rank": 3},
                {"bioguide": "D4", "name": "D4", "party": "minority", "rank": 4},
            ],
            "SLIN": [
                {"bioguide": "R2", "name": "R2", "party": "majority", "rank": 1, "title": "Chairman"},
                {"bioguide": "R9", "name": "R9", "party": "majority", "rank": 9, "title": "Ex Officio"},
                {"bioguide": "D2", "name": "D2", "party": "minority", "rank": 1, "title": "Vice Chairman"},
                {"bioguide": "D3", "name": "D3", "party": "minority", "rank": 2},
            ],
            "SSFR01": [{"bioguide": "R1", "name": "R1", "party": "majority", "rank": 1}],
        }
        self.current = committees.parse_membership(
            membership, [{"thomas_id": "SSFR", "name": "Foreign Relations"}]
        )
        # D1 retires. Chamber: 56 D, 44 R (only caucus share matters).
        ids_d = ["D2", "D3", "D4"] + [f"DX{i}" for i in range(53)]
        ids_r = ["R1", "R2", "R3", "R4", "R5", "R9"] + [f"RX{i}" for i in range(38)]
        self.baseline = pd.DataFrame(
            {"bioguide_id": ids_d + ids_r, "caucus": ["D"] * len(ids_d) + ["R"] * len(ids_r)}
        )
        self.assign, self.lead = committees.project(self.current, self.baseline)
        self.lead = self.lead.set_index("committee_id")

    def test_subcommittees_ignored(self):
        self.assertNotIn("SSFR01", set(self.current["committee_id"]))

    def test_majority_flips_and_next_democrat_chairs(self):
        self.assertEqual(self.lead.loc["SSFR", "chair_bioguide"], "D2")
        self.assertEqual(self.lead.loc["SSFR", "ranking_bioguide"], "R1")

    def test_seat_split_bumps_and_vacancies(self):
        row = self.lead.loc["SSFR"]
        self.assertEqual((row["majority_seats"], row["minority_seats"]), (5, 4))
        self.assertEqual(row["majority_vacancies"], 2)  # 3 Democrats stay for 5 seats
        self.assertEqual(row["minority_bumped"], 1)     # 5 Republicans for 4 seats
        bumped = self.assign[(self.assign["status"] == "bumped")]
        self.assertEqual(bumped["bioguide_id"].tolist(), ["R5"])

    def test_one_post_per_senator_and_vice_chair_title(self):
        # D2 already chairs SSFR (Super A, processed first), so D3 takes Intelligence.
        self.assertEqual(self.lead.loc["SLIN", "chair_bioguide"], "D3")
        # R2 is the top Republican on SLIN; R1 holds SSFR ranking, R2 is free.
        self.assertEqual(self.lead.loc["SLIN", "ranking_bioguide"], "R2")
        self.assertEqual(self.lead.loc["SLIN", "ranking_title"], "Vice Chairman")

    def test_ex_officio_not_seated(self):
        self.assertNotIn("R9", self.assign["bioguide_id"].tolist())

    def test_senator_summary_flags(self):
        s = committees.senator_summary(self.assign).set_index("bioguide_id")
        self.assertTrue(s.loc["D2", "on_SSFR"])
        self.assertTrue(s.loc["D2", "on_SLIN"])
        self.assertEqual(s.loc["D2", "leadership"], "Chair:SSFR")
        self.assertEqual(s.loc["D2", "n_super_a"], 1)


if __name__ == "__main__":
    unittest.main()
