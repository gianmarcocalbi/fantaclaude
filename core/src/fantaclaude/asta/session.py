"""The night's rules: what the FantaAstaLive session says it is playing.

Session settings are authoritative for the night, and every change to them
is surfaced (spec, "Session settings are authoritative for the night").
They come from the feed's `settings` node -- or, with no session, from the
league's own settings row the pinned run was priced under, which is what
makes the offline board the committed board.

Observed 2026-08-23 (captured/fantaastalive-state-2026-08-23.json, the
app's local state, pre-auction): `settings.budget 500`, `settings.game 2`,
`settings.participants 2`, `settings.roles = {gk: [3, 3], def: [8, 8],
mid: [8, 8], atk: [6, 6], mov: [22, 22], size: [25, 25]}`, with `mov = def
+ mid + atk` and `size = gk + mov`: exact counts, one per game type. The
pairs are read as [classic, mantra] -- the spec's reading, confirmable only
at the rehearsal; with every observed pair equal the reading cannot yet be
wrong, and `_pair` is the one place to change if it is. In Mantra the
enforced buckets are `gk` and `mov` (`teams[].missingPlayers` counts those
two). The league's own bounds are ranges (2-6 goalkeepers, 23-40 players),
so every bucket is carried as a (low, high) pair either way, and a
session's exact count is the pair (n, n).

Nothing here assumes the game. A session states it in `settings.game`; a
league row states it in its profile's `tipo` (design spec: "league type --
`tipo: 2`; `mods` = the eleven official Mantra schemes"). `sroles` is *not*
that discriminator -- the spec's open question 2 settles it, "`sroles: 2`
showing roster bounds that are not Mantra-shaped is no contradiction:
Mantra governs lineup roles, not roster composition" -- it is the number of
roster role groups, and so the guard on whether `minrl`/`maxrl` may be
indexed as [goalkeepers, outfield] at all.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import duckdb

from fantaclaude.values import is_number

GAME_CLASSIC = 1
GAME_MANTRA = 2
GAME_NAMES = {GAME_CLASSIC: "classic", GAME_MANTRA: "Mantra"}
# `rosters.sroles`: how many role groups minrl/maxrl bound. At 2 they are
# [goalkeepers, outfield] (2+21 = msltc 23, 6+34 = xsltc 40); at any other
# count this reader would report the wrong bucket as the outfield bound, so
# it refuses rather than mis-indexing.
ROSTER_BUCKETS = 2
Bounds = tuple[int, int]


class SessionError(ValueError):
    """The settings lack a number the board cannot be priced without, or carry a shape this reader does not know."""


@dataclass(frozen=True)
class SessionSettings:
    budget: int
    goalkeepers: Bounds
    outfield: Bounds
    size: Bounds
    game: int
    team_count: int
    source: str                              # "session" | "league"
    raw: dict[str, Any] = field(default_factory=dict)
    # The formations the league allows. Read off the league's own settings, so
    # it is empty for a session-sourced view; the board carries the league's.
    modules: tuple[str, ...] = ()

    @property
    def is_mantra(self) -> bool:
        return self.game == GAME_MANTRA

    def to_dict(self) -> dict[str, Any]:
        return {"budget": self.budget, "goalkeepers": list(self.goalkeepers), "outfield": list(self.outfield),
                "size": list(self.size), "game": self.game, "team_count": self.team_count, "source": self.source}


def _count(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionError(f"{where} is {value!r}; expected a count")
    return value


def _game(value: Any, where: str) -> int:
    """The game in play, stated and never assumed: 1 classic, 2 Mantra."""
    if isinstance(value, bool) or value not in GAME_NAMES:
        raise SessionError(f"{where} is {value!r}; expected {GAME_CLASSIC} (classic) or {GAME_MANTRA} (Mantra)")
    return int(value)


def _pair(roles: Mapping[str, Any], key: str, game: int) -> Bounds:
    """One bucket of settings.roles as (low, high): a [classic, mantra] pair
    read by the game in play, or a bare count for either game.

    The [classic, mantra] reading is an assumption over an undocumented
    field -- every pair observed on 2026-08-23 held two equal counts, so
    nothing yet distinguishes it from [mantra, classic] or from a
    (min, max). It is isolated here on purpose: if the rehearsal shows the
    pair means something else, this function is the only thing to change.
    """
    value = roles.get(key)
    if isinstance(value, list) and len(value) == 2:
        n = _count(value[1 if game == GAME_MANTRA else 0], f"settings.roles.{key}")
        return n, n
    if isinstance(value, int) and not isinstance(value, bool):
        n = _count(value, f"settings.roles.{key}")
        return n, n
    raise SessionError(f"settings.roles.{key} is {value!r}; expected a [classic, mantra] pair of counts")


def session_from_feed(settings: Mapping[str, Any], *, team_count: int) -> SessionSettings:
    budget = settings.get("budget")
    if not is_number(budget) or budget < 0:
        raise SessionError(f"settings.budget is {budget!r}; expected the credits per team")
    game = _game(settings.get("game"), "settings.game")
    roles = settings.get("roles")
    if not isinstance(roles, Mapping):
        raise SessionError(f"settings.roles is {roles!r}; expected the per-bucket counts")
    gk, mov, size = _pair(roles, "gk", game), _pair(roles, "mov", game), _pair(roles, "size", game)
    if size[0] != gk[0] + mov[0]:
        # FA-rb8-460, 2026-09-03: the live session shipped gk 4, mov 28, size 30
        # and the mirror refused it mid-auction. Refusing is the right default --
        # the roster shape is what every completion is solved against, so a wrong
        # guess poisons every max price. Here `size` and `mov` agree with each
        # other (28 + 2 = 30) and only `gk` does not, so the goalkeeper count is
        # the outlier and is derived rather than trusted; the operator confirmed
        # 2 goalkeepers. Announced on stdout, never silent.
        derived = (size[0] - mov[0], size[1] - mov[1])
        if derived[0] < 0 or derived[1] < 0:
            raise SessionError(f"settings.roles.mov {mov[0]} exceeds size {size[0]}; the session is unusable")
        print(f"SESSION INCONSISTENT: roles.size {size[0]} != gk {gk[0]} + mov {mov[0]}; "
              f"size and mov agree, so deriving gk {derived[0]} (session said {gk[0]})", flush=True)
        gk = derived
    return SessionSettings(int(budget), gk, mov, size, game, int(team_count), "session", dict(settings))


def session_from_league(*, budget: int, team_count: int, roster_min: int, roster_max: int,
                        minrl: list[int], maxrl: list[int], game: int) -> SessionSettings:
    """The league's own bounds, read the way the design reads `sroles: 2`:
    minrl / maxrl are [goalkeepers, outfield]. The game is the caller's to
    state -- it is a league rule, so it is read from the league, never
    assumed here. Every bound is validated: the stored payload demonstrably
    carries nulls (`under`, `cteam`), and SessionError is the only error
    this function raises."""
    if not isinstance(minrl, (list, tuple)) or not isinstance(maxrl, (list, tuple)) or len(minrl) < 2 or len(maxrl) < 2:
        raise SessionError(f"minrl {minrl!r} / maxrl {maxrl!r} are not the two bounds per bucket this reader indexes")
    return SessionSettings(_count(budget, "budget"),
                           (_count(minrl[0], "minrl[0]"), _count(maxrl[0], "maxrl[0]")),
                           (_count(minrl[1], "minrl[1]"), _count(maxrl[1], "maxrl[1]")),
                           (_count(roster_min, "roster_min"), _count(roster_max, "roster_max")),
                           _game(game, "game"), _count(team_count, "team_count"), "league")


def league_bounds(con: duckdb.DuckDBPyConnection, snapshot_id: int) -> SessionSettings:
    """The settings row a run was priced under, as bounds."""
    row = con.execute("SELECT budget, team_count, roster_min, roster_max, payload, modules FROM league_settings "
                      "WHERE snapshot_id = ?", [snapshot_id]).fetchone()
    if row is None:
        raise SessionError(f"league_settings has no snapshot {snapshot_id}")
    payload = row[4] if isinstance(row[4], dict) else json.loads(row[4])
    rosters = payload.get("rosters") or {}
    minrl, maxrl = rosters.get("minrl") or [], rosters.get("maxrl") or []
    if any(v is None for v in row[:4]) or len(minrl) < 2 or len(maxrl) < 2:
        raise SessionError(f"league_settings snapshot {snapshot_id} lacks the budget, the team count or the roster bounds")
    sroles = rosters.get("sroles")
    if sroles != ROSTER_BUCKETS:
        raise SessionError(f"league_settings snapshot {snapshot_id} has rosters.sroles {sroles!r}; minrl/maxrl are read "
                           f"as [goalkeepers, outfield] only at {ROSTER_BUCKETS} role groups")
    out = session_from_league(budget=row[0], team_count=row[1], roster_min=row[2], roster_max=row[3],
                              minrl=minrl, maxrl=maxrl,
                              game=_game((payload.get("profile") or {}).get("tipo"),
                                         f"league_settings snapshot {snapshot_id}: profile.tipo"))
    mods = tuple(str(m) for m in (row[5] or []))      # a column, not a payload key
    return replace(out, modules=mods) if mods else out


def _span(bounds: Bounds) -> str:
    return str(bounds[0]) if bounds[0] == bounds[1] else f"{bounds[0]}-{bounds[1]}"


def compare(session: SessionSettings, league: SessionSettings) -> list[str]:
    """What the session plays that the league's settings do not allow --
    surfaced loudly at connect, before bidding opens; the session wins for
    the night (spec, "Session settings are authoritative for the night")."""
    out: list[str] = []
    if session.budget != league.budget:
        out.append(f"budget: the session plays {session.budget} credits, the league says {league.budget}")
    if session.team_count != league.team_count:
        out.append(f"teams: {session.team_count} in the session, {league.team_count} in the league")
    if session.game != league.game:
        out.append(f"game: the session is {GAME_NAMES[session.game]} ({session.game}), "
                   f"the league is {GAME_NAMES[league.game]} ({league.game})")
    for name, ours, theirs in (("goalkeepers", session.goalkeepers, league.goalkeepers),
                               ("outfield", session.outfield, league.outfield), ("roster", session.size, league.size)):
        if ours[0] < theirs[0] or ours[1] > theirs[1]:
            out.append(f"{name}: the session fills {_span(ours)}, the league allows {_span(theirs)}")
    return out
