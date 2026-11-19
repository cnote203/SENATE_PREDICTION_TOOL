"""Offline tests for the empty-Congress fallback path."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import config  # noqa: E402
from senate_sim.ingest import http  # noqa: E402
from senate_sim.roster import build_baseline  # noqa: E402
from senate_sim.seat_changes import apply_seat_changes  # noqa: E402

EMPTY = json.dumps({"members": [], "pagination": {"count": 0}}).encode()
FULL = json.dumps({"members": [{"bioguideId": "A1"}], "pagination": {}}).encode()


def _has_members(body: bytes) -> bool:
    return bool(json.loads(body).get("members"))


class EmptyResponsesAreNotCached(unittest.TestCase):
    def _fake_get(self, body):
        resp = mock.Mock(content=body)
        resp.raise_for_status = lambda: None
        session = mock.Mock()
        session.get.return_value = resp
        return mock.patch.object(http, "_session", return_value=session)

    def test_empty_body_not_written(self):
        with tempfile.TemporaryDirectory() as d, self._fake_get(EMPTY):
            http.cached_get("https://x/y", cache_dir=Path(d), is_usable=_has_members)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_stale_empty_cache_is_refetched(self):
        with tempfile.TemporaryDirectory() as d:
            path = http._cache_path("https://x/y", {}, Path(d))
            path.write_bytes(EMPTY)
            with self._fake_get(FULL):
                body = http.cached_get("https://x/y", cache_dir=Path(d), is_usable=_has_members)
            self.assertEqual(body, FULL)
            self.assertEqual(path.read_bytes(), FULL)

    def test_api_key_not_in_cache_name(self):
        a = http._cache_path("https://x/y", {"api_key": "SECRET1"}, Path("."))
        b = http._cache_path("https://x/y", {"api_key": "SECRET2"}, Path("."))
        self.assertEqual(a, b)
        self.assertNotIn("SECRET", a.name)


class SeatChanges(unittest.TestCase):
    def setUp(self):
        self.current = pd.DataFrame(
            [
                {"bioguide_id": "R1", "name": "Old R", "state": "Michigan", "api_party": "Republican"},
                {"bioguide_id": "D1", "name": "Stay D", "state": "Maine", "api_party": "Democratic"},
            ]
        )

    def _changes(self, **overrides):
        row = {"state": "MI", "outgoing_bioguide": "R1", "incoming_name": "New D",
               "incoming_party": "Democratic", "incoming_bioguide": "", "caucus_with_d": ""}
        row.update(overrides)
        return pd.DataFrame([row])

    def test_swap_with_placeholder_id(self):
        out = apply_seat_changes(self.current, self._changes())
        self.assertNotIn("R1", out["bioguide_id"].tolist())
        self.assertIn("NEW-MI-1", out["bioguide_id"].tolist())
        self.assertEqual(len(out), 2)

    def test_unknown_outgoing_rejected(self):
        with self.assertRaises(ValueError):
            apply_seat_changes(self.current, self._changes(outgoing_bioguide="ZZZ"))

    def test_independent_caucusing_with_d(self):
        changes = self._changes(incoming_party="Independent", caucus_with_d="yes")
        baseline = build_baseline(apply_seat_changes(self.current, changes),
                                  pd.DataFrame(columns=["bioguide_id", "nominate_dim1"]))
        new = baseline[baseline["bioguide_id"] == "NEW-MI-1"].iloc[0]
        self.assertEqual(new["caucus"], "D")
        self.assertTrue(new["freshman"])

    def test_states_normalized_to_codes(self):
        baseline = build_baseline(apply_seat_changes(self.current, self._changes()),
                                  pd.DataFrame(columns=["bioguide_id", "nominate_dim1"]))
        self.assertEqual(sorted(baseline["state"]), ["ME", "MI"])


class StateCodes(unittest.TestCase):
    def test_names_and_codes(self):
        self.assertEqual(config.state_code("New Hampshire"), "NH")
        self.assertEqual(config.state_code("tx"), "TX")


if __name__ == "__main__":
    unittest.main()
