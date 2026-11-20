"""Senate committee hearing schedule from the Congress.gov committee-meeting API.

The list endpoint returns meeting IDs ordered by update date, and can be
filtered by update date only. Each meeting's date, title, committees, status,
witnesses and video links come from the item endpoint, so we list everything
updated recently and then keep meetings whose own date falls in the window.

Congress.gov tags every Senate event as type "Meeting". Senate committee
system codes look like "ssfr00" (full committee) or "ssfr09" (subcommittee 09
of SSFR), which map onto the thomas IDs used everywhere else in this project.

Live viewing: Senate committees stream their own hearings on their websites,
and C-SPAN carries many of them. C-SPAN allows non-commercial sites to use its
coverage of federal government events with attribution, but its three cable
channel streams sit behind pay-TV sign-in, so this module never builds links
into those streams. It records official pages to open, plus any embeddable
URL listed by hand in data/manual/hearing_streams.csv.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from senate_sim import config
from senate_sim.ingest.http import cached_get

PAGE_SIZE = 250
SYSTEM_CODE = re.compile(r"^(s[slp][a-z]{2})(\d{2})$", re.I)

# Hosts whose URLs the web app may place in an iframe. Anything else is shown
# as a link that opens in a new tab.
EMBED_HOSTS = {
    "www.c-span.org", "c-span.org",
    "www.youtube.com", "youtube.com", "www.youtube-nocookie.com", "youtu.be",
    "www.senate.gov", "senate.gov",
}
STREAM_COLUMNS = ["event_id", "embed_url", "label", "note"]

# AUDIT: C-SPAN search URL format; confirm it opens a results page.
CSPAN_SEARCH = "https://www.c-span.org/search/?searchtype=Videos&query={q}"
CONGRESS_MEETING = "https://www.congress.gov/event/{congress}-congress/senate-event/{event_id}"


# GovInfo Link Service: stable links to official text, no API key needed.
GOVINFO_BILL = "https://www.govinfo.gov/link/bills/{congress}/{type}/{number}?link-type=html"
GOVINFO_HEARING = "https://www.govinfo.gov/link/chrg/{congress}/{jacket}"
CONGRESS_NOMINATION = "https://www.congress.gov/nomination/{congress}-congress/{number}"


def bill_link(congress, bill_type: str, number) -> str | None:
    t = re.sub(r"[^a-z]", "", str(bill_type).lower())
    if not (congress and t and str(number).strip()):
        return None
    return GOVINFO_BILL.format(congress=int(congress), type=t, number=str(number).strip())


def transcripts(meeting: dict) -> list[dict]:
    """Printed hearing transcripts (GPO jacket numbers) linked through GovInfo."""
    raw = meeting.get("hearingTranscript")
    found = _items(raw) if not (isinstance(raw, dict) and "jacketNumber" in raw) else [raw]
    out = []
    for t in found:
        jacket = str(t.get("jacketNumber") or "").strip()
        if not jacket:
            continue
        if re.fullmatch(r"\d{5}", jacket):  # GovInfo writes jackets as 12-345
            jacket = f"{jacket[:2]}-{jacket[2:]}"
        out.append({"jacket": jacket, "url": GOVINFO_HEARING.format(congress=meeting.get("congress"), jacket=jacket)})
    return out


def ordinal(n: int) -> str:
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def congress_for(day: date) -> int:
    """Congress in session on a given day (each starts on 3 January of an odd year)."""
    year = day.year
    if year % 2 == 1 and (day.month, day.day) < (1, 3):
        year -= 1
    return (year - 1789) // 2 + 1


def parse_system_code(code: str) -> tuple[str, str | None] | None:
    """'ssfr09' -> ('SSFR', '09'); 'ssfr00' -> ('SSFR', None)."""
    m = SYSTEM_CODE.match(code or "")
    if not m:
        return None
    parent, sub = m.group(1).upper(), m.group(2)
    return parent, (None if sub == "00" else sub)


def _items(container) -> list:
    """Congress.gov wraps some lists as {"item": [...]} and some as bare lists."""
    if isinstance(container, dict):
        container = container.get("item", [])
    if isinstance(container, dict):
        container = [container]
    return container if isinstance(container, list) else []


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace(" ", "T", 1) if "T" not in value else value.strip()
    text = text.replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def committee_index(committees_current: list[dict]) -> dict:
    """thomas_id -> {name, url, subcommittees: {code: name}} from congress-legislators."""
    out = {}
    for c in committees_current:
        out[c["thomas_id"]] = {
            "name": c.get("name", c["thomas_id"]),
            "url": (c.get("url") or "").rstrip("/"),
            "subcommittees": {s["thomas_id"]: s.get("name", "") for s in c.get("subcommittees", [])},
        }
    return out


def sector_index(modules) -> dict:
    """thomas_id -> list of sector module names that watch that committee."""
    out: dict[str, list[str]] = {}
    for m in modules:
        for cid in m.committees:
            out.setdefault(cid, []).append(m.name)
    return out


def load_streams(path: Path) -> dict:
    """event_id -> {url, label, note} for hand-entered embeddable streams."""
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            eid = (row.get("event_id") or "").strip()
            url = (row.get("embed_url") or "").strip()
            if eid and url:
                out[eid] = {"url": url, "label": (row.get("label") or "").strip(),
                            "note": (row.get("note") or "").strip()}
    return out


def embeddable(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.netloc.lower() in EMBED_HOSTS


def youtube_embed(url: str) -> str | None:
    """Return a privacy-mode embed URL for a YouTube watch/short/embed link."""
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|live/)|youtu\.be/)([\w-]{11})", url or "")
    return f"https://www.youtube-nocookie.com/embed/{m.group(1)}" if m else None


def normalize(item: dict, committees: dict, sectors: dict, streams: dict) -> dict | None:
    """Turn one committee-meeting item payload into the record the web app reads."""
    meeting = item.get("committeeMeeting", item)
    if str(meeting.get("chamber", "")).lower() != "senate":
        return None
    when = parse_when(meeting.get("date"))
    if when is None:
        return None

    held_by = []
    for c in _items(meeting.get("committees")):
        parsed = parse_system_code(c.get("systemCode", ""))
        if not parsed:
            continue
        parent, sub = parsed
        info = committees.get(parent, {})
        held_by.append({
            "id": parent,
            "name": info.get("name") or c.get("name", parent),
            "sub": sub,
            "subName": info.get("subcommittees", {}).get(sub) if sub else None,
            "apiName": c.get("name"),
        })
    if not held_by:
        return None

    event_id = str(meeting.get("eventId", ""))
    congress = meeting.get("congress")
    loc = meeting.get("location") or {}
    location = " ".join(x for x in [loc.get("room"), loc.get("building")] if x and not set(x) <= {"-"})
    if not location and loc.get("address"):
        location = "Field hearing"

    videos = []
    for v in _items(meeting.get("videos")):
        url = v.get("url")
        if url:
            videos.append({"name": v.get("name") or "Video", "url": url, "embed": youtube_embed(url)})

    related = meeting.get("relatedItems") or {}
    agenda = []
    for b in _items(related.get("bills")):
        label = f"{b.get('type', '')} {b.get('number', '')}".strip()
        if label:
            agenda.append({"label": label, "kind": "bill",
                           "url": bill_link(b.get("congress") or meeting.get("congress"), b.get("type", ""), b.get("number", ""))})
    for n in _items(related.get("nominations")):
        if not n.get("number"):
            continue
        part = f"-{n['part']}" if n.get("part") not in (None, "", "00") else ""
        agenda.append({"label": f"PN{n['number']}{part}", "kind": "nomination",
                       "url": CONGRESS_NOMINATION.format(congress=ordinal(n.get("congress") or meeting.get("congress")),
                                                         number=f"{n['number']}{part}")})

    lead = held_by[0]
    title = re.sub(r"\s+", " ", meeting.get("title") or "").strip() or "Committee meeting"
    committee_url = committees.get(lead["id"], {}).get("url") or ""

    links = {
        "congress": CONGRESS_MEETING.format(congress=ordinal(congress), event_id=event_id) if congress and event_id else None,
        "committee": committee_url or None,
        "committeeHearings": f"{committee_url}/hearings" if committee_url else None,
        "cspan": CSPAN_SEARCH.format(q=quote_plus(f"{lead['name'].replace('Senate ', '')} {title[:80]}")),
    }

    embed = None
    manual = streams.get(event_id)
    if manual:
        url = youtube_embed(manual["url"]) or manual["url"]
        if embeddable(url):
            embed = {"url": url, "label": manual["label"] or "Stream", "note": manual["note"], "source": "manual"}
    if embed is None:
        for v in videos:
            if v["embed"]:
                embed = {"url": v["embed"], "label": v["name"], "note": "", "source": "congress.gov"}
                break

    sector_ids = sorted({s for c in held_by for s in sectors.get(c["id"], [])})
    return {
        "id": event_id,
        "congress": congress,
        "start": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": meeting.get("meetingStatus") or "Scheduled",
        "title": title,
        "committees": held_by,
        "sectors": sector_ids,
        "location": location or None,
        "witnesses": [{"name": w.get("name"), "position": w.get("position"), "organization": w.get("organization")}
                      for w in _items(meeting.get("witnesses")) if w.get("name")],
        "agenda": agenda,
        "transcripts": transcripts(meeting),
        "videos": videos,
        "embed": embed,
        "links": links,
        "updated": meeting.get("updateDate"),
    }


def in_window(record: dict, now: datetime, days_back: int, days_ahead: int) -> bool:
    start = parse_when(record["start"])
    return now - timedelta(days=days_back) <= start <= now + timedelta(days=days_ahead)


# --- network ---------------------------------------------------------------

def _has_list(body: bytes) -> bool:
    try:
        return "committeeMeetings" in json.loads(body)
    except ValueError:
        return False


def _has_item(body: bytes) -> bool:
    try:
        return "committeeMeeting" in json.loads(body)
    except ValueError:
        return False


def list_meetings(congress: int, updated_since: datetime, cache_dir: Path, refresh: bool) -> list[dict]:
    """Every Senate meeting in a Congress updated since a given time (paged)."""
    api_key = config.congress_api_key()
    url = f"{config.CONGRESS_API_BASE}/committee-meeting/{congress}/senate"
    out, offset = [], 0
    while True:
        params = {"api_key": api_key, "format": "json", "limit": PAGE_SIZE, "offset": offset,
                  "fromDateTime": updated_since.strftime("%Y-%m-%dT%H:%M:%SZ")}
        body = json.loads(cached_get(url, params, cache_dir=cache_dir, refresh=refresh, is_usable=_has_list))
        page = _items(body.get("committeeMeetings"))
        out.extend(page)
        if len(page) < PAGE_SIZE or not (body.get("pagination") or {}).get("next"):
            return out
        offset += PAGE_SIZE


def fetch_meeting(congress: int, event_id: str, cache_dir: Path, refresh: bool) -> dict:
    url = f"{config.CONGRESS_API_BASE}/committee-meeting/{congress}/senate/{event_id}"
    params = {"api_key": config.congress_api_key(), "format": "json"}
    return json.loads(cached_get(url, params, cache_dir=cache_dir, refresh=refresh, is_usable=_has_item))
