"""The XI actually fielded, read back from the platform (spec, "Closing the
loop"): the GET the lega's own formazioni page makes for one match, captured
2026-09-05 from a logged-in browser session, never guessed (Phase 3b, Task
13, Step 1). Raw JSON scrubbed of emails under data/raw/lineup/.

The plan first guessed a per-TEAM GET (`team_id`, `matchday` as query
parameters). The captured request is per MATCH instead -- five path
segments, no query parameters -- and returns both sides at once:
`idcomp` (the competition), the competition's own `mday`, the Serie A
`cmday` it maps to, and the two teams' ids. Resolving those segments for
"my lineup at giornata N" is therefore two lookups first: which
competition (`select_competition`, fed by `FantacalcioAPI.competitions` --
read live every call, never a `league.yml` guess: the id, and the
competition's own first/last giornata, are a plain API lookup, not a fact
the API cannot express), then which round of its calendar
(`resolve_match`, shared with the MCP's own `get_lineup` tool -- see
`fantacalcio_mcp.calendar`'s own docstring for why it lives there and not
here). Both are fetched fresh every time -- two more reads against a real
account, under the same rule as everything else this module touches.
"""

from __future__ import annotations

from typing import Any

from fantacalcio_mcp.api import FantacalcioAPI
from fantacalcio_mcp.calendar import MatchNotFoundError
from fantacalcio_mcp.calendar import resolve_match as _resolve_match

from fantaclaude.analysis.weekly.submitted import Submission
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.league.settings import without_emails
from fantaclaude.model.modules import Module, assign
from fantaclaude.model.roles import Role

# From the capture (capture-facts.md, Task 13): where the module, the
# eleven, the bench and each entry's player id live on a match side.
MODULE_KEY, XI_KEY, BENCH_KEY, PLAYER_ID_KEY = "mdl", "starts", "bench", "pid"


class LineupShapeError(ValueError):
    """The response is not the lineup object this adapter was written against."""


class CompetitionSelectionError(LineupShapeError):
    """The account's own competitions list does not resolve to exactly one
    competition without help."""


class CompetitionRangeError(LineupShapeError):
    """The giornata asked for (explicit or defaulted) is outside this
    competition's own sDay-eDay range."""


def select_competition(competitions: list[dict[str, Any]] | None, *,
                       competition_id: int | None = None) -> dict[str, Any]:
    """The one competition to read the calendar and the lineup from.

    Read live from `FantacalcioAPI.competitions` every call -- `idcomp` is
    a plain API lookup (`competitions-shape.md`, Task 13's review), not a
    fact `league.yml` should pin. Only one competition was ever observed in
    this league, but the payload is a list, so `[0]` is never taken
    blindly: an explicit `competition_id` (a CLI `--competition`) picks by
    id when there is more than one; without it, exactly one competition
    must exist, or this refuses rather than guessing which one is meant.
    """
    rows = list(competitions or [])
    if competition_id is not None:
        for row in rows:
            if int(row.get("id", -1)) == competition_id:
                return row
        known = ", ".join(str(row.get("id")) for row in rows) or "none"
        raise CompetitionSelectionError(f"competition {competition_id} is not among this league's own competitions "
                                        f"({known})")
    if not rows:
        raise CompetitionSelectionError("this league has no competition configured yet")
    if len(rows) > 1:
        ids = ", ".join(str(row.get("id")) for row in rows)
        raise CompetitionSelectionError(f"this league runs {len(rows)} competitions ({ids}) -- pass --competition "
                                        f"to pick one")
    return rows[0]


def resolve_giornata(competition: dict[str, Any], *, ahead_giornata: int | None, requested: int | None) -> int:
    """The giornata to read back: `requested`, checked against this
    competition's own `sDay`/`eDay`, or -- when nothing was requested --
    the newest FINISHED giornata (`ahead_giornata`, `target_round`'s own
    answer, minus one), clamped to both `sDay` and `eDay`.

    `target_round` knows nothing of a *calendario*'s own start or end: a
    competition with `sDay: 3` (this league's own) has no giornata 2 to
    read back at all, and one whose own calendar has already finished
    while Serie A's has not would otherwise hand `resolve_match` a
    championship matchday past `eDay` that this competition never played
    either -- either way, `ahead_giornata - 1` alone would fail with an
    unrelated "not in this competition's calendar" message instead of
    naming the actual cause. Both bounds are checked the same way, on
    either side of the range.
    """
    start = int(competition.get("sDay") or 1)
    end = int(competition.get("eDay") or 38)
    name = competition.get("name") or "this competition"
    if requested is not None:
        if not (start <= requested <= end):
            raise CompetitionRangeError(f"giornata {requested} is outside {name}'s own range ({start}-{end})")
        return requested
    if ahead_giornata is None:
        raise CompetitionRangeError("no giornata to default to -- pass --giornata")
    resolved = ahead_giornata - 1
    if resolved < start:
        raise CompetitionRangeError(f"no giornata of {name} (starts at {start}) has finished yet -- pass --giornata")
    if resolved > end:
        raise CompetitionRangeError(f"giornata {resolved} is outside {name}'s own range ({start}-{end}) -- pass --giornata")
    return resolved


def resolve_match(calendar: Any, *, championship_matchday: int, team_id: int) -> tuple[int, int, int, int]:
    """(mday, cmday, home_tid, away_tid) for the one round of `calendar` at
    `championship_matchday` whose match involves `team_id`.

    Delegates to `fantacalcio_mcp.calendar.resolve_match` -- shared, not
    duplicated, with the MCP's own `get_lineup` tool -- and translates its
    `MatchNotFoundError` into this module's own `LineupShapeError`, so
    every failure this adapter raises is one type.
    """
    try:
        return _resolve_match(calendar, championship_matchday=championship_matchday, team_id=team_id)
    except MatchNotFoundError as exc:
        raise LineupShapeError(str(exc)) from exc


async def fetch_lineup(api: FantacalcioAPI, store: RawStore, *, team_id: int, requested_giornata: int | None,
                       ahead_giornata: int | None = None, competition_id: int | None = None,
                       league: str | None = None) -> tuple[RawFile, dict[str, Any], int]:
    """The whole read-back fetch, in order: the account's own competitions
    (`select_competition` picks the one to use), the giornata this call
    will actually read (`resolve_giornata`, checked against that
    competition's own `sDay`/`eDay`), its calendar (never cached: read
    fresh every call), the five segments `resolve_match` resolves to, then
    the one match GET -- scrubbed of emails (a no-op against the observed
    shape, applied anyway as the same defence in depth every other fetch in
    this codebase carries) and written once. Returns the raw file, the
    payload, and the giornata actually read (which the caller may not have
    known in advance, when it was defaulted).
    """
    competitions = await api.competitions(league=league)
    competition = select_competition(competitions, competition_id=competition_id)
    idcomp = int(competition["id"])
    giornata = resolve_giornata(competition, ahead_giornata=ahead_giornata, requested=requested_giornata)
    calendar = await api.competition_calendar(idcomp, league=league)
    mday, cmday, home_tid, away_tid = resolve_match(calendar, championship_matchday=giornata, team_id=team_id)
    payload = without_emails(await api.lineup(idcomp, mday, cmday, home_tid, away_tid, league=league))
    return store.write("lineup", payload, label=f"{team_id}-{giornata:02d}"), payload, giornata


def _side(payload: dict[str, Any], team_id: int) -> dict[str, Any]:
    """Home or away, whichever side's `tid` is mine -- never a fixed
    position. The capture's own match had me on `away` (Task 13's Ruling
    2): a version that assumed `home` would silently read an opponent's XI."""
    home, away = payload.get("home") or {}, payload.get("away") or {}
    if home.get("tid") == team_id:
        return home
    if away.get("tid") == team_id:
        return away
    raise LineupShapeError(f"neither side of this match is team {team_id} "
                           f"(home {home.get('tid')!r}, away {away.get('tid')!r})")


def load_lineup(payload: dict[str, Any], *, team_id: int, roster: list[RosterPlayer], modules: dict[str, Module],
                allowed: list[str]) -> Submission:
    """My own side of the match, mapped onto a `Submission` via the
    module's own slot table -- `assign(chosen, [roles...], allow_adapted=True)`,
    the same fit `build_submission`'s non-`preserve_slots` branch already
    trusts -- never the platform's own `starts`/`bench` array order paired
    positionally with `modules.yml`'s slot list. That array order is not a
    slot order this repo can rely on: giornata 3's own away side (module
    `3421`, the review that caught this) puts a `C/W` player at `starts[5]`,
    which `3421`'s fifth *slot* (`M`) accepts neither naturally nor adapted
    -- a positional zip would have recorded a slot the module forbids, into
    an immutable table and a permanent parquet. `assign` returning `None`
    (the eleven, however ordered, cannot legally field this module at all)
    is refused rather than guessed at.

    `allowed` is accepted for the same shape `build_submission` takes but
    is not consulted for that same reason as before: a module the league's
    settings no longer permit is still what actually happened on the
    platform, and the read-back's job is to record that, not to
    second-guess it.

    A player id neither in `roster` nor known any other way is recorded as
    `#<pid>` and named in `Submission.warnings` rather than refused:
    `roster` is the *current* roster snapshot while this reads back an
    already-finished giornata, so a player who has since left is expected
    drift, not a malformed response -- unlike a missing, duplicate, or
    XI/bench-overlapping `pid`, which is refused outright below. His true
    roles being unknowable here, he is treated as fitting any slot (a
    wildcard) so one stale id cannot make `assign` refuse an otherwise
    legal eleven; the warning is how that uncertainty survives instead of
    disappearing into a confident-looking slot label.
    """
    by_id = {p.player_id: p for p in roster}
    side = _side(payload, team_id)
    module = str(side.get(MODULE_KEY) or "")
    if module not in modules:
        raise LineupShapeError(f"{MODULE_KEY}={module!r} is not a module this repo knows")
    chosen = modules[module]

    def pid_of(entry: dict[str, Any]) -> int:
        value = entry.get(PLAYER_ID_KEY) if isinstance(entry, dict) else None
        if not isinstance(value, int):
            raise LineupShapeError(f"an entry carries no {PLAYER_ID_KEY}: {entry!r}")
        return value

    eleven = [pid_of(entry) for entry in side.get(XI_KEY) or []]
    bench = [pid_of(entry) for entry in side.get(BENCH_KEY) or []]
    if len(eleven) != len(chosen.slots):
        raise LineupShapeError(f"{XI_KEY} carries {len(eleven)} players, the module has {len(chosen.slots)} slots")
    if len(set(eleven)) != len(eleven):
        raise LineupShapeError(f"{XI_KEY} repeats a player id: {eleven!r}")
    overlap = sorted(set(eleven) & set(bench))
    if overlap:
        raise LineupShapeError(f"{XI_KEY} and {BENCH_KEY} share player id(s) {overlap}")

    unknown = sorted(pid for pid in {*eleven, *bench} if pid not in by_id)
    warnings = tuple(f"player_id {pid} named by the platform is not on my current roster snapshot "
                     f"(it may have moved since this giornata was played)" for pid in unknown)
    wildcard = frozenset(Role)          # unknown to the roster: fits everywhere, never blocks assign

    def roles_of(pid: int) -> frozenset[Role]:
        return by_id[pid].roles if pid in by_id else wildcard

    def name(pid: int) -> str:
        return by_id[pid].name if pid in by_id else f"#{pid}"

    legal = assign(chosen, [roles_of(pid) for pid in eleven], allow_adapted=True)
    if legal is None:
        raise LineupShapeError(f"those {len(chosen.slots)} cannot field {chosen.label} legally (natural or adapted "
                              f"fits only) -- the platform read-back does not match this repo's own module table")
    xi = [{"slot": chosen.slots[k].label, "player_id": eleven[legal[k]], "name": name(eleven[legal[k]])}
         for k in range(len(chosen.slots))]
    return Submission(module, xi, [{"player_id": pid, "name": name(pid)} for pid in bench], None, warnings)
