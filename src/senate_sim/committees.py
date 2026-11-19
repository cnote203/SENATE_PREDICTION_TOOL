"""Senate committee rosters: current assignments and a projection to the new Congress.

Current data comes from congress-legislators (scraped from senate.gov). The
projection to the 120th Congress applies, per full committee:

1. Departing senators leave. Ex officio members are set aside (they hold seats
   by virtue of another office and do not vote on the Intelligence Committee).
2. Sides follow the new majority caucus. Each party keeps its own internal order.
3. Seats are re-split to match the chamber ratio. If a side now has more members
   than seats, its lowest-ranked members are bumped; if fewer, open seats are
   listed as vacancies for incoming senators.
4. Leadership: on each side the highest-ranked remaining member becomes Chair
   (majority) or Ranking Member (minority), skipping anyone who already holds
   MAX_LEADERSHIP_POSTS, processing Super A committees first.

Everything after step 1 is a projection, not a record. Party conferences make
these decisions in January, and the AUDIT notes in config.py apply.
"""
from __future__ import annotations

import math

import pandas as pd

from senate_sim import config

MEMBER_COLUMNS = ["committee_id", "bioguide_id", "member_name", "side", "rank", "title"]


def parse_membership(membership: dict, committees: list[dict] | None = None) -> pd.DataFrame:
    """Flatten committee-membership-current.json to rows for tiered Senate full committees."""
    names = {c.get("thomas_id"): c.get("name") for c in (committees or [])}
    rows = []
    for cid, members in membership.items():
        if cid not in config.COMMITTEE_TIERS:
            continue
        for m in members:
            rows.append(
                {
                    "committee_id": cid,
                    "committee_name": names.get(cid, cid),
                    "tier": config.COMMITTEE_TIERS[cid],
                    "bioguide_id": m.get("bioguide"),
                    "member_name": m.get("name"),
                    "side": m.get("party"),
                    "rank": m.get("rank"),
                    "title": m.get("title") or "",
                }
            )
    return pd.DataFrame(rows)


def _seat_split(total: int, majority_share: float) -> tuple[int, int]:
    # AUDIT: the organizing resolution sets real ratios; this keeps a one-seat
    # minimum majority edge and otherwise follows the chamber split.
    majority = max(round(total * majority_share), total // 2 + 1)
    return majority, total - majority


def project(
    current: pd.DataFrame,
    baseline: pd.DataFrame,
    new_majority: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Project committee membership onto the baseline roster.

    Returns (assignments, leadership):
      assignments  one row per seat: members kept, bumped, and open vacancies
      leadership   one row per committee: projected chair and top minority member
    """
    counts = baseline["caucus"].value_counts()
    new_majority = new_majority or counts.idxmax()
    majority_share = counts.get(new_majority, 0) / len(baseline)

    caucus = baseline.set_index("bioguide_id")["caucus"]
    staying = current[current["bioguide_id"].isin(caucus.index)].copy()
    staying = staying[staying["title"].str.lower() != "ex officio"]
    staying["caucus"] = staying["bioguide_id"].map(caucus)
    staying["side"] = (staying["caucus"] == new_majority).map({True: "majority", False: "minority"})

    meta = (
        current[["committee_id", "committee_name", "tier"]]
        .drop_duplicates("committee_id")
        .assign(_order=lambda d: d["tier"].map(config.TIER_ORDER))
        .sort_values(["_order", "committee_id"])
    )
    voting_size = (
        current[current["title"].str.lower() != "ex officio"].groupby("committee_id").size()
    )

    seats, leaders = [], []
    held = {"majority": {}, "minority": {}}
    for _, c in meta.iterrows():
        cid = c["committee_id"]
        maj_seats, min_seats = _seat_split(int(voting_size.get(cid, 0)), majority_share)
        row = {"committee_id": cid, "committee_name": c["committee_name"], "tier": c["tier"],
               "majority_seats": maj_seats, "minority_seats": min_seats}

        for side, target in (("majority", maj_seats), ("minority", min_seats)):
            members = staying[(staying["committee_id"] == cid) & (staying["side"] == side)]
            members = members.sort_values("rank")
            for i, (_, m) in enumerate(members.iterrows(), start=1):
                seats.append({
                    "committee_id": cid, "committee_name": c["committee_name"], "tier": c["tier"],
                    "side": side, "bioguide_id": m["bioguide_id"], "member_name": m["member_name"],
                    "caucus": m["caucus"], "side_rank": i,
                    "status": "member" if i <= target else "bumped",
                })
            for j in range(len(members) + 1, target + 1):
                seats.append({
                    "committee_id": cid, "committee_name": c["committee_name"], "tier": c["tier"],
                    "side": side, "bioguide_id": None, "member_name": None,
                    "caucus": new_majority if side == "majority" else None,
                    "side_rank": j, "status": "vacancy",
                })

            top_title = "Chair" if side == "majority" else config.MINORITY_TOP_TITLE.get(cid, "Ranking Member")
            chosen = None
            for _, m in members.head(target).iterrows():
                if held[side].get(m["bioguide_id"], 0) < config.MAX_LEADERSHIP_POSTS:
                    chosen = m
                    break
            if chosen is not None:
                held[side][chosen["bioguide_id"]] = held[side].get(chosen["bioguide_id"], 0) + 1
            key = "chair" if side == "majority" else "ranking"
            row[f"{key}_title"] = top_title
            row[f"{key}_bioguide"] = None if chosen is None else chosen["bioguide_id"]
            row[f"{key}_name"] = None if chosen is None else chosen["member_name"]
            row[f"{side}_vacancies"] = max(target - len(members), 0)
            row[f"{side}_bumped"] = max(len(members) - target, 0)
        leaders.append(row)

    assignments = pd.DataFrame(seats)
    leadership = pd.DataFrame(leaders)

    titles = {}
    for _, l in leadership.iterrows():
        if l["chair_bioguide"]:
            titles[(l["committee_id"], l["chair_bioguide"])] = l["chair_title"]
        if l["ranking_bioguide"]:
            titles[(l["committee_id"], l["ranking_bioguide"])] = l["ranking_title"]
    assignments["title"] = [
        titles.get((cid, bid), "") for cid, bid in zip(assignments["committee_id"], assignments["bioguide_id"])
    ]
    return assignments, leadership


def senator_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    """Per-senator committee columns to join onto the baseline roster."""
    seated = assignments[assignments["status"] == "member"]
    grouped = seated.groupby("bioguide_id")
    out = pd.DataFrame({
        "committees": grouped["committee_id"].apply(lambda s: ";".join(sorted(s))),
        "n_super_a": grouped["tier"].apply(lambda s: int((s == "Super A").sum())),
    })
    lead = seated[seated["title"] != ""]
    out["leadership"] = lead.groupby("bioguide_id").apply(
        lambda d: ";".join(f"{t}:{c}" for t, c in zip(d["title"], d["committee_id"])),
        include_groups=False,
    )
    for cid in config.FOREIGN_POLICY_COMMITTEES:
        out[f"on_{cid}"] = out["committees"].str.split(";").map(lambda ids, c=cid: c in ids)
    out["leadership"] = out["leadership"].fillna("")
    return out.reset_index()
