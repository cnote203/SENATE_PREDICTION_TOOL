"""Offline tests for the hearing schedule parser."""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from senate_sim import policy  # noqa: E402
from senate_sim.ingest import hearings as h  # noqa: E402

COMMITTEES = h.committee_index([
    {"thomas_id": "SSFR", "name": "Senate Committee on Foreign Relations", "url": "http://www.foreign.senate.gov/",
     "subcommittees": [{"thomas_id": "09", "name": "Near East, South Asia, Central Asia, and Counterterrorism"}]},
    {"thomas_id": "SSFI", "name": "Senate Committee on Finance", "url": "http://www.finance.senate.gov/"},
    {"thomas_id": "SSRA", "name": "Senate Committee on Rules and Administration", "url": "http://www.rules.senate.gov/"},
])
SECTORS = h.sector_index(policy.all_modules())


def payload(**over):
    m = {
        "eventId": 338149, "congress": 119, "chamber": "Senate", "type": "Meeting",
        "title": "Hearings to examine  U.S. policy toward Iran.", "meetingStatus": "Scheduled",
        "date": "2026-11-24T15:00:00Z", "updateDate": "2026-11-18T20:01:00Z",
        "committees": [{"systemCode": "ssfr09", "name": "Near East Subcommittee"}],
        "location": {"room": "419", "building": "Dirksen Senate Office Building"},
        "witnesses": [{"name": "Jane Doe", "position": "Envoy", "organization": "State"}],
        "relatedItems": {"bills": [{"type": "S", "number": "1582"}],
                         "nominations": {"item": [{"number": "512", "part": "00"}]}},
    }
    m.update(over)
    return {"committeeMeeting": m}


class Parsing(unittest.TestCase):
    def test_system_codes(self):
        self.assertEqual(h.parse_system_code("ssfr00"), ("SSFR", None))
        self.assertEqual(h.parse_system_code("SSFR09"), ("SSFR", "09"))
        self.assertEqual(h.parse_system_code("slin00"), ("SLIN", None))
        self.assertIsNone(h.parse_system_code("hsii24"))

    def test_congress_for(self):
        self.assertEqual(h.congress_for(date(2026, 11, 20)), 119)
        self.assertEqual(h.congress_for(date(2027, 1, 2)), 119)
        self.assertEqual(h.congress_for(date(2027, 1, 3)), 120)

    def test_ordinal(self):
        self.assertEqual([h.ordinal(n) for n in (119, 120, 121, 122, 111)], ["119th", "120th", "121st", "122nd", "111th"])

    def test_dates_with_space_or_missing_zone(self):
        self.assertEqual(h.parse_when("2023-03-24 13:00:00Z").hour, 13)
        self.assertEqual(h.parse_when("2023-03-24T13:00:00").tzinfo, timezone.utc)
        self.assertIsNone(h.parse_when("not a date"))

    def test_normalize_maps_committee_sector_and_links(self):
        r = h.normalize(payload(), COMMITTEES, SECTORS, {})
        self.assertEqual(r["committees"][0]["id"], "SSFR")
        self.assertEqual(r["committees"][0]["subName"], "Near East, South Asia, Central Asia, and Counterterrorism")
        self.assertIn("foreign_policy", r["sectors"])
        self.assertEqual(r["title"], "Hearings to examine U.S. policy toward Iran.")
        self.assertEqual(r["location"], "419 Dirksen Senate Office Building")
        self.assertEqual([a["label"] for a in r["agenda"]], ["S 1582", "PN512"])
        self.assertEqual(r["agenda"][0]["url"], "https://www.govinfo.gov/link/bills/119/s/1582?link-type=html")
        self.assertEqual(r["agenda"][1]["url"], "https://www.congress.gov/nomination/119th-congress/512")
        self.assertEqual(r["transcripts"], [])
        self.assertEqual(r["links"]["committeeHearings"], "http://www.foreign.senate.gov/hearings")
        self.assertIn("119th-congress/senate-event/338149", r["links"]["congress"])
        self.assertIsNone(r["embed"])

    def test_finance_hearing_tags_several_sectors(self):
        r = h.normalize(payload(committees={"item": [{"systemCode": "ssfi00"}]}), COMMITTEES, SECTORS, {})
        self.assertGreaterEqual(len(r["sectors"]), 2)

    def test_untracked_committee_kept_without_sector(self):
        r = h.normalize(payload(committees=[{"systemCode": "ssra00"}]), COMMITTEES, SECTORS, {})
        self.assertEqual(r["sectors"], [])

    def test_house_and_dateless_meetings_dropped(self):
        self.assertIsNone(h.normalize(payload(chamber="House"), COMMITTEES, SECTORS, {}))
        self.assertIsNone(h.normalize(payload(date=None), COMMITTEES, SECTORS, {}))
        self.assertIsNone(h.normalize(payload(committees=[{"systemCode": "hsii24"}]), COMMITTEES, SECTORS, {}))

    def test_embed_rules(self):
        yt = {"338149": {"url": "https://www.youtube.com/watch?v=abcdefghijk", "label": "Committee feed", "note": ""}}
        r = h.normalize(payload(), COMMITTEES, SECTORS, yt)
        self.assertEqual(r["embed"]["url"], "https://www.youtube-nocookie.com/embed/abcdefghijk")
        bad = {"338149": {"url": "https://example.com/player", "label": "", "note": ""}}
        self.assertIsNone(h.normalize(payload(), COMMITTEES, SECTORS, bad)["embed"])
        plain = {"338149": {"url": "http://www.c-span.org/x", "label": "", "note": ""}}
        self.assertIsNone(h.normalize(payload(), COMMITTEES, SECTORS, plain)["embed"])
        vid = payload(videos={"item": [{"name": "Feed", "url": "https://youtu.be/abcdefghijk"}]})
        self.assertEqual(h.normalize(vid, COMMITTEES, SECTORS, {})["embed"]["source"], "congress.gov")

    def test_transcripts_list_or_single(self):
        one = h.normalize(payload(hearingTranscript={"jacketNumber": "61234"}), COMMITTEES, SECTORS, {})
        self.assertEqual(one["transcripts"][0]["url"], "https://www.govinfo.gov/link/chrg/119/61-234")
        many = h.normalize(payload(hearingTranscript=[{"jacketNumber": "61-234"}, {"jacketNumber": ""}]), COMMITTEES, SECTORS, {})
        self.assertEqual(len(many["transcripts"]), 1)
        self.assertEqual(h.bill_link(119, "S.J.Res.", 18), "https://www.govinfo.gov/link/bills/119/sjres/18?link-type=html")
        self.assertIsNone(h.bill_link(None, "S", 1))

    def test_window(self):
        r = h.normalize(payload(), COMMITTEES, SECTORS, {})
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        self.assertTrue(h.in_window(r, now, 14, 28))
        self.assertFalse(h.in_window(r, now, 14, 2))

    def test_streams_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_text("event_id,embed_url,label,note\n338149,https://www.c-span.org/x,C-SPAN,\n,https://x,,\n")
            self.assertEqual(list(h.load_streams(p)), ["338149"])
            self.assertEqual(h.load_streams(Path(d) / "missing.csv"), {})


if __name__ == "__main__":
    unittest.main()
