"""The round and its deadlines, read off `fixtures`, never off the stored
`status.mday` (spec, "The round and the deadline are read off the calendar;
`status` is the cross-check")."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import duckdb

from fantaclaude.analysis.weekly.errors import ForecastError
from fantaclaude.timeutil import to_db


@dataclass(frozen=True)
class Round:
    season_id: int
    giornata: int
    first_kickoff: datetime          # naive UTC, as fixtures stores it
    last_kickoff: datetime
    matches: int

    def to_dict(self) -> dict[str, Any]:
        return {"season_id": self.season_id, "giornata": self.giornata,
                "first_kickoff": self.first_kickoff.isoformat(sep=" ", timespec="minutes"),
                "last_kickoff": self.last_kickoff.isoformat(sep=" ", timespec="minutes"), "matches": self.matches}


@dataclass(frozen=True)
class PlayerFixture:
    kickoff: datetime                # naive UTC, as fixtures stores it
    home: bool
    opponent_short: str | None


def player_fixtures(con: duckdb.DuckDBPyConnection, probabili_file_id: int) -> dict[int, PlayerFixture]:
    """Each listed player's own match, joined by `team_short` the way the
    staleness check already joins; a player whose club the page did not
    resolve, or whose match has no kickoff, is absent -- the caller falls
    back to the round's first kickoff and says so (open question 18)."""
    rows = con.execute(
        "SELECT p.player_id, f.kickoff, f.home_short = p.team_short, "
        "CASE WHEN f.home_short = p.team_short THEN f.away_short ELSE f.home_short END "
        "FROM probabili p JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = p.season_id "
        "AND f.giornata = p.giornata AND (f.home_short = p.team_short OR f.away_short = p.team_short) "
        "WHERE p.file_id = ? AND p.team_short IS NOT NULL AND f.kickoff IS NOT NULL", [probabili_file_id]).fetchall()
    return {int(pid): PlayerFixture(kickoff, bool(home), opponent) for pid, kickoff, home, opponent in rows}


def target_round(con: duckdb.DuckDBPyConnection, now: datetime, *, season_id: int,
                 giornata: int | None = None) -> Round:
    """The giornata to forecast: the first whose last kickoff is still ahead
    (a giornata in progress is still the target -- and late), or the one asked for."""
    rows = con.execute(
        "SELECT giornata, min(kickoff), max(kickoff), count(*) FROM v_fixtures_current "
        "WHERE competition = 'SA' AND season_id = ? AND giornata IS NOT NULL AND kickoff IS NOT NULL "
        "GROUP BY giornata ORDER BY giornata", [season_id]).fetchall()
    if not rows:
        raise ForecastError(f"no Serie A fixtures for season {season_id} -- run `fantaclaude ingest calendar`")
    rounds = [Round(season_id, int(g), first, last, int(n)) for g, first, last, n in rows]
    if giornata is not None:
        for r in rounds:
            if r.giornata == giornata:
                return r
        raise ForecastError(f"giornata {giornata} is not in the season {season_id} calendar")
    when = to_db(now)
    for r in rounds:
        if r.last_kickoff > when:
            return r
    raise ForecastError(f"every giornata of season {season_id} has kicked off -- pass --giornata to write one late")


MATCHDAY_READ_WINDOW = timedelta(days=5)


def matchday_cross_check(con: duckdb.DuckDBPyConnection, round_: Round) -> str | None:
    """A warning when the freshest roster snapshot's mday/mstr disagree with
    the calendar's round; None when they agree, nothing has been fetched, or
    the snapshot has nothing current to say.

    `ingest rosters` runs "when the rosters changed, never to check"
    (CLAUDE.md), so the freshest snapshot can sit unchanged for weeks --
    without a recency bound, a matchday-3 read from the day after the
    auction would forever be compared against giornata 7's calendar, and the
    (backwards) advice to pass --giornata would fire on every `lineup` run
    from giornata 4 onward, drowning the real warnings beside it (review
    finding 4, 2026-09-04). So the read is compared only when it is recent
    enough, relative to THIS round's kickoff, to plausibly still describe
    it -- `fetched_at` no more than `MATCHDAY_READ_WINDOW` before
    `round_.first_kickoff` (a read fetched at or after kickoff is always
    compared, however "stale" it looks by this measure)."""
    row = con.execute("SELECT matchday, matchday_start, fetched_at FROM roster_snapshots "
                      "WHERE matchday IS NOT NULL ORDER BY snapshot_id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    matchday, start, fetched_at = row
    if round_.first_kickoff - fetched_at > MATCHDAY_READ_WINDOW:
        return None
    if int(matchday) == round_.giornata and (start is None or start == round_.first_kickoff):
        return None
    return (f"the league API's status read on {fetched_at:%Y-%m-%d %H:%M} UTC said matchday {matchday} starting "
            f"{start}; the calendar says giornata {round_.giornata} at {round_.first_kickoff} -- if the platform is "
            f"fresher, pass --giornata")


STALE_COMPILATION = timedelta(days=1)


def compilation_staleness(con: duckdb.DuckDBPyConnection, giornata: int,
                          probabili_file_id: int) -> list[str]:
    """Warnings, one per match, when that match's OWN probabili compilation
    stamp predates that match's OWN kickoff by more than a day (spec: "the
    lineup command warns when a match's compilation predates its own
    kickoff by more than a day, instead of treating Tuesday's guess as
    Saturday's team news").

    No `season_id` parameter: the query is already fully scoped by
    `p.file_id = ?` (one probabili page, one season, one giornata) and the
    `f.season_id = p.season_id` join carries the season across to
    `fixtures` -- a `season_id` argument here would be redundant with
    `probabili_file_id` and, worse, invite a reader to assume it does some
    scoping the query does not actually use it for (review finding 13,
    2026-09-04).

    The join to `fixtures` is on `team_short`, not `club_slug`: the
    fantacalcio.it URL slug `club_slug` carries (e.g. "inter") has no
    established mapping anywhere in this codebase to the listone short code
    `fixtures.home_short`/`away_short` use, and inventing one here would be
    exactly the kind of club fact CLAUDE.md says must never come from
    memory. `team_short` needs no such mapping: `ingest probabili` already
    resolves it per row from the listone by `player_id` (the reliable join
    the page gives for free), the same listone `resolve_team` fills
    `fixtures.home_short`/`away_short` from at calendar ingest -- so the two
    columns already speak the same short code. A match with no listone-known
    player on the page (an unmapped `player_id`, `team_short IS NULL` for
    both its clubs) is not checked; that is the honest limit of this join,
    not a fallback to the round's first kickoff."""
    rows = con.execute(
        "SELECT f.home_short, f.away_short, f.kickoff, min(p.updated_at) FROM probabili p "
        "JOIN v_fixtures_current f ON f.competition = 'SA' AND f.season_id = p.season_id AND f.giornata = p.giornata "
        "AND (f.home_short = p.team_short OR f.away_short = p.team_short) "
        "WHERE p.file_id = ? AND p.updated_at IS NOT NULL AND f.kickoff IS NOT NULL "
        "GROUP BY f.home_short, f.away_short, f.kickoff", [probabili_file_id]).fetchall()
    warnings = []
    for home, away, kickoff, updated_at in rows:
        age = kickoff - updated_at
        if age > STALE_COMPILATION:
            warnings.append(f"{home}-{away} (giornata {giornata}): probabili compiled {updated_at:%Y-%m-%d %H:%M} UTC, "
                            f"{age.days} day(s) before its own kickoff {kickoff:%Y-%m-%d %H:%M} UTC -- treat its p_start as stale")
    return sorted(warnings)


def uncompiled_match_warning(giornata: int, uncompiled: int, fetched_at: str) -> str:
    """The one sentence for "N matches of this giornata are not yet
    compiled", shared with the CLI's plain-text renderer so the two can
    never fall out of sync. `_render_lineup` used to find this specific
    entry in `warnings` by substring-matching a fragment of THIS sentence
    hardcoded a second time in `cli/app.py` -- reword it here and the
    renderer's match silently stops firing: the UNCOMPILED line vanishes
    from its near-header position while the same warning reappears,
    undeduplicated, at the bottom (review finding 10, 2026-09-04). Calling
    this one function from both places instead means a reword changes both
    at once, by construction, and the renderer can select the entry by
    exact equality against what it independently builds from
    `page['uncompiled']`/`page['fetched_at']`, never by parsing prose."""
    return f"{uncompiled} match(es) of giornata {giornata} not yet compiled on the page fetched {fetched_at} UTC"
