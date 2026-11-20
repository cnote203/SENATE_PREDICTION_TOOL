"""Fetch the Senate committee hearing schedule for the web app's HEARINGS mode.

Usage (PowerShell):
    $env:CONGRESS_API_KEY = "<your key>"
    python scripts\\fetch_hearings.py [--days-back 14] [--days-ahead 28]

Writes web/public/data/hearings.json. Hearings are tagged with every policy
sector whose committees hold them (see each module's `committees` list).

To give a hearing an in-app player, add a row to
data/manual/hearing_streams.csv with its event ID and an embeddable URL from
c-span.org, YouTube or senate.gov (for example the src of C-SPAN's embed
code). Other hosts are shown as links.

The script runs on a schedule in .github/workflows/pages.yml when the
repository has a CONGRESS_API_KEY secret.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from senate_sim import config, policy  # noqa: E402
from senate_sim.ingest import hearings, legislators  # noqa: E402

OUT = PROJECT_ROOT / "web" / "public" / "data" / "hearings.json"
STREAMS = PROJECT_ROOT / "data" / "manual" / "hearing_streams.csv"
CACHE = config.RAW_DIR / "hearings"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days-back", type=int, default=14)
    ap.add_argument("--days-ahead", type=int, default=28)
    ap.add_argument("--updated-days", type=int, default=75,
                    help="list meetings updated within this many days (default 75)")
    ap.add_argument("--use-cache", action="store_true", help="reuse cached API answers instead of refreshing")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    refresh = not args.use_cache
    committees = hearings.committee_index(legislators.fetch_json("committees-current.json", refresh=refresh))
    sectors = hearings.sector_index(policy.all_modules())
    streams = hearings.load_streams(STREAMS)

    congresses = sorted({hearings.congress_for((now - timedelta(days=args.days_back)).date()),
                         hearings.congress_for((now + timedelta(days=args.days_ahead)).date())})
    since = now - timedelta(days=args.updated_days)

    records, skipped = [], 0
    for congress in congresses:
        listed = hearings.list_meetings(congress, since, CACHE, refresh)
        print(f"{congress}th Congress: {len(listed)} Senate meetings updated since {since:%Y-%m-%d}")
        for item in listed:
            event_id = str(item.get("eventId", ""))
            if not event_id:
                continue
            try:
                payload = hearings.fetch_meeting(congress, event_id, CACHE, refresh)
            except Exception as exc:  # one bad item should not sink the schedule
                skipped += 1
                print(f"  skipped {event_id}: {exc}")
                continue
            rec = hearings.normalize(payload, committees, sectors, streams)
            if rec and hearings.in_window(rec, now, args.days_back, args.days_ahead):
                records.append(rec)

    records.sort(key=lambda r: (r["start"], r["committees"][0]["id"]))
    unknown = sorted(set(streams) - {r["id"] for r in records})
    out = {
        "generated": now.isoformat(timespec="minutes").replace("+00:00", "Z"),
        "window": {"from": (now - timedelta(days=args.days_back)).date().isoformat(),
                   "to": (now + timedelta(days=args.days_ahead)).date().isoformat()},
        "source": "Congress.gov API committee-meeting endpoint",
        "hearings": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")

    tagged = sum(1 for r in records if r["sectors"])
    print(f"\n{len(records)} hearings in window ({tagged} tied to a sector, "
          f"{sum(1 for r in records if r['embed'])} with an in-app player)")
    if skipped:
        print(f"{skipped} meetings skipped after errors")
    if unknown:
        print(f"hearing_streams.csv rows with no hearing in the window: {', '.join(unknown)}")
    print(f"wrote {args.out.relative_to(PROJECT_ROOT) if args.out.is_relative_to(PROJECT_ROOT) else args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
