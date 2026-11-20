"""Where individual Senate roll-call votes come from.

Two interchangeable sources, both returning (meta, votes) for a roll call
identified by (congress, session, senate.gov roll number):

  voteview  (default) bulk CSVs from voteview.com:
              S{congress}_rollcalls.csv  one row per roll call; `clerk_rollnumber`
                                         is the senate.gov number within a session
              S{congress}_votes.csv      one row per member per roll call
              S{congress}_members.csv    icpsr -> bioguide_id, party
            Lags senate.gov by days to weeks.
  senate    senate.gov roll-call XML. Authoritative and same-day, but senate.gov
            refuses automated requests from many networks (HTTP 403).

votes columns: bioguide_id, party (D/R/I), vote_cast, yea (1.0 / 0.0 / NaN)
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

from senate_sim import config
from senate_sim.ingest import senate_votes
from senate_sim.ingest.http import cached_get

VOTEVIEW_BASE = "https://voteview.com/static/data/out"
PARTY = {100: "D", 200: "R", 328: "I"}
# Voteview cast codes: 1-3 yea (incl. paired/announced), 4-6 nay, 7-9 present or not voting.
CAST = {1: "Yea", 2: "Yea", 3: "Yea", 4: "Nay", 5: "Nay", 6: "Nay",
        7: "Present", 8: "Not Voting", 9: "Not Voting"}


def normalize_bill(text) -> str:
    """'S.J.Res. 18' and 'SJRES18' both become 'SJRES18'."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def find_voteview(rollcalls: pd.DataFrame, bill: str, question: str | None) -> list[dict]:
    """Senate roll calls on a bill whose question matches a regular expression."""
    rc = rollcalls.copy()
    rc["_bill"] = rc["bill_number"].map(normalize_bill)
    hit = rc[rc["_bill"] == normalize_bill(bill)]
    if question:
        hit = hit[hit["vote_question"].fillna("").str.contains(question, case=False, regex=True)]
    return [{"session": int(r["session"]), "roll": int(r["clerk_rollnumber"]),
             "date": str(r.get("date", ""))[:10], "question": str(r.get("vote_question", ""))}
            for _, r in hit.sort_values(["session", "clerk_rollnumber"]).iterrows()]


def first_year(congress: int) -> int:
    return 1787 + 2 * congress


class VoteviewSource:
    name = "voteview"

    def __init__(self, cache_dir: Path = config.RAW_DIR, refresh: bool = False):
        self.cache_dir, self.refresh = cache_dir, refresh
        self._loaded: dict[int, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}

    def _csv(self, kind: str, congress: int) -> pd.DataFrame:
        url = f"{VOTEVIEW_BASE}/{kind}/S{congress}_{kind}.csv"
        body = cached_get(url, cache_dir=self.cache_dir, refresh=self.refresh,
                          is_usable=lambda b: b"congress" in b[:500])
        return pd.read_csv(io.BytesIO(body), low_memory=False)

    def load(self, congress: int):
        if congress not in self._loaded:
            self._loaded[congress] = prepare_voteview(
                self._csv("rollcalls", congress), self._csv("votes", congress),
                self._csv("members", congress), congress,
            )
        return self._loaded[congress]

    def get(self, congress: int, session: int, roll: int):
        rollcalls, votes, members = self.load(congress)
        return select_voteview(rollcalls, votes, members, congress, session, roll)

    def find(self, congress: int, bill: str, question: str | None = None) -> list[dict]:
        rollcalls, _, _ = self.load(congress)
        return find_voteview(rollcalls, bill, question)


def prepare_voteview(rollcalls, votes, members, congress):
    rc = rollcalls[rollcalls["chamber"].astype(str).str.title() == "Senate"].copy()
    if "session" not in rc or rc["session"].isna().all():
        years = pd.to_datetime(rc["date"]).dt.year
        rc["session"] = np.where(years == first_year(congress), 1, 2)
    rc["session"] = rc["session"].astype(int)
    rc["clerk_rollnumber"] = rc["clerk_rollnumber"].astype(int)
    mem = members[members["chamber"].astype(str).str.title() == "Senate"]
    mem = mem[["icpsr", "bioguide_id", "party_code"]].drop_duplicates("icpsr")
    return rc, votes, mem


def select_voteview(rollcalls, votes, members, congress, session, roll):
    hit = rollcalls[(rollcalls["session"] == session) & (rollcalls["clerk_rollnumber"] == roll)]
    if hit.empty:
        raise LookupError(
            f"Voteview has no Senate roll call {congress}-{session}-{roll} yet "
            "(it lags senate.gov by days to weeks)."
        )
    rc = hit.iloc[0]
    v = votes[(votes["rollnumber"] == rc["rollnumber"])
              & (votes["chamber"].astype(str).str.title() == "Senate")]
    v = v.merge(members, on="icpsr", how="left")
    v = v[v["cast_code"] != 0]
    out = pd.DataFrame({
        "bioguide_id": v["bioguide_id"].to_numpy(),
        "party": v["party_code"].map(PARTY).fillna("I").to_numpy(),
        "vote_cast": v["cast_code"].map(CAST).fillna("Not Voting").to_numpy(),
    })
    out["yea"] = out["vote_cast"].map({"Yea": 1.0, "Nay": 0.0})
    meta = {
        "congress": congress, "session": session, "roll": roll,
        "date": str(rc.get("date", "")),
        "question": str(rc.get("vote_question", "") or ""),
        "document": str(rc.get("bill_number", "") or rc.get("vote_desc", "") or ""),
        "yeas": int(rc.get("yea_count", (out["yea"] == 1).sum())),
        "nays": int(rc.get("nay_count", (out["yea"] == 0).sum())),
    }
    return meta, out


class SenateSource:
    name = "senate"

    def __init__(self, lis_map: dict[str, str], cache_dir: Path = config.RAW_DIR, refresh: bool = False):
        self.lis_map, self.cache_dir, self.refresh = lis_map, cache_dir, refresh

    def find(self, congress: int, bill: str, question: str | None = None) -> list[dict]:
        raise LookupError("Looking roll calls up by bill needs --source voteview.")

    def get(self, congress: int, session: int, roll: int):
        meta, members = senate_votes.fetch_vote(congress, session, roll, self.cache_dir, self.refresh)
        coded = senate_votes.code_votes(members, self.lis_map)
        return meta, coded[["bioguide_id", "party", "vote_cast", "yea"]]


def make_source(name: str, lis_map: dict[str, str], refresh: bool = False):
    if name == "senate":
        return SenateSource(lis_map, refresh=refresh)
    return VoteviewSource(refresh=refresh)
