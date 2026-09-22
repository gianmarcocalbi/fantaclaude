"""The platform's own scoring of one lega match, read back with the XI (spec,
"Calibration: what 3c ships").

The match GET `ingest lineup` makes answers, once the round is calculated
(`cal` true), every listed player's voto (`scr`), fantavoto (`cscr`), malus
count (`m`) and sixteen-count event string (`b`), and per side the total
(`tot`) and the points. Checked on 2026-09-22 against the voti, all 138 rows
of giornate 3-5 agree: `scr` is the Fantacalcio sheet's voto and `cscr` is
`scoring.fantavoto` less one point per `m`. Two sentinels stand for a missing
voto, each beside `cscr` 100: `scr` 56, a player absent from the voti sheet,
and `scr` 55, a senza voto. Anything else outside 0-10 is refused by name --
a new sentinel must fail loud, never land as a voto of 57.

A response for a round not yet calculated (`cal` false: 56 everywhere, `b`
null, a partial `tot`) is not recorded: its numbers are not the round's.
Recording is keyed by the raw file's sha256, so the same bytes twice are one
row and `record_from_disk` can walk data/raw/lineup/ at any time. `b` is kept
verbatim and read by nothing: seven of its sixteen positions are identified,
the rest are not.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db
from fantaclaude.values import is_number

ABSENT_SCR, SV_SCR, NO_CSCR = 56, 55, 100
STATUS_VOTO, STATUS_SV, STATUS_ABSENT = "voto", "sv", "absent"
PARTS = (("starts", "xi"), ("bench", "bench"))          # the platform's key -> ours


class MatchScoresShapeError(ValueError):
    """The response is not the calculated match this parser was written against."""


class NoSeasonCalendar(RuntimeError):
    """The season's Serie A calendar is missing, so a raw file cannot be placed in it."""


@dataclass(frozen=True)
class PlayerScore:
    team_id: int
    player_id: int
    part: str
    position: int
    status: str
    voto: float | None
    fantavoto: float | None
    malus: int
    events: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class MatchScores:
    giornata: int
    competition_id: int
    matchday: int
    home_team: int
    away_team: int
    home_module: str | None
    away_module: str | None
    home_total: float
    away_total: float
    home_points: int
    away_points: int
    result: str | None
    sign: str | None
    players: tuple[PlayerScore, ...]


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MatchScoresShapeError(f"{what} is not an integer: {value!r}")
    return value


def _number(value: Any, what: str) -> float:
    if not is_number(value):
        raise MatchScoresShapeError(f"{what} is not a number: {value!r}")
    return float(value)


def _text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _player(entry: Any, *, team_id: int, part: str, position: int) -> PlayerScore:
    if not isinstance(entry, dict):
        raise MatchScoresShapeError(f"team {team_id} {part}[{position}] is not an object: {entry!r}")
    pid = _int(entry.get("pid"), f"team {team_id} {part}[{position}].pid")
    scr = _number(entry.get("scr"), f"player {pid} scr")
    cscr = _number(entry.get("cscr"), f"player {pid} cscr")
    malus = _int(entry.get("m") or 0, f"player {pid} m")
    if malus < 0:
        raise MatchScoresShapeError(f"player {pid}: a negative malus count {malus}")
    events = entry.get("b")
    if events is not None and not isinstance(events, str):
        raise MatchScoresShapeError(f"player {pid}: b is not a string: {events!r}")
    if scr in (ABSENT_SCR, SV_SCR):
        if cscr != NO_CSCR:
            raise MatchScoresShapeError(f"player {pid}: scr {scr:g} is a missing-voto sentinel but cscr is {cscr:g}, "
                                        f"not {NO_CSCR}")
        status = STATUS_ABSENT if scr == ABSENT_SCR else STATUS_SV
        return PlayerScore(team_id, pid, part, position, status, None, None, malus, events, entry)
    if not 0 <= scr <= 10:
        raise MatchScoresShapeError(f"player {pid}: scr {scr:g} is neither a voto nor a known sentinel "
                                    f"({SV_SCR} senza voto, {ABSENT_SCR} absent)")
    if cscr == NO_CSCR:
        raise MatchScoresShapeError(f"player {pid}: a voto of {scr:g} beside cscr {NO_CSCR}, the missing-voto sentinel")
    return PlayerScore(team_id, pid, part, position, STATUS_VOTO, scr, cscr, malus, events, entry)


def oriented_result(result: str | None, mine_home: bool) -> str | None:
    """The platform's `res` ('4-1', home first) with my goals first."""
    if result is None:
        return None
    home, sep, away = result.partition("-")
    return result if mine_home or not sep else f"{away}-{home}"


def _side(payload: dict[str, Any], key: str) -> dict[str, Any]:
    side = payload.get(key)
    if not isinstance(side, dict):
        raise MatchScoresShapeError(f"{key} is missing or not an object")
    return side


def parse_match(payload: dict[str, Any]) -> MatchScores | None:
    """The calculated match, or None while `cal` says the round is not calculated yet."""
    if payload.get("cal") is not True:
        return None
    home, away = _side(payload, "home"), _side(payload, "away")
    players: list[PlayerScore] = []
    for side in (home, away):
        tid = _int(side.get("tid"), "a side's tid")
        for key, part in PARTS:
            entries = side.get(key)
            if not isinstance(entries, list):
                raise MatchScoresShapeError(f"team {tid} {key} is not a list")
            players += [_player(entry, team_id=tid, part=part, position=i) for i, entry in enumerate(entries)]
    return MatchScores(
        giornata=_int(payload.get("cmday"), "cmday"), competition_id=_int(payload.get("idcomp"), "idcomp"),
        matchday=_int(payload.get("mday"), "mday"), home_team=home["tid"], away_team=away["tid"],
        home_module=_text(home.get("mdl")), away_module=_text(away.get("mdl")),
        home_total=_number(home.get("tot"), "home tot"), away_total=_number(away.get("tot"), "away tot"),
        home_points=_int(home.get("points"), "home points"), away_points=_int(away.get("points"), "away points"),
        result=_text(payload.get("res")), sign=_text(payload.get("sign")), players=tuple(players))


@dataclass(frozen=True)
class RecordedMatch:
    raw_path: str
    giornata: int | None
    calculated: bool
    file_id: int | None
    duplicate: bool
    players: int
    home_team: int | None = None
    away_team: int | None = None
    home_total: float | None = None
    away_total: float | None = None
    result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_match(con: duckdb.DuckDBPyConnection, raw: RawFile, payload: dict[str, Any], *,
                 season_id: int) -> RecordedMatch:
    """One match_files row and its match_scores, appended once per raw file.
    A round not yet calculated records nothing and says so; the same bytes
    recorded before are named as a duplicate, with the file they became."""
    match = parse_match(payload)
    if match is None:
        cmday = payload.get("cmday")
        giornata = cmday if isinstance(cmday, int) and not isinstance(cmday, bool) else None
        return RecordedMatch(str(raw.path), giornata, False, None, False, 0)
    common = {"home_team": match.home_team, "away_team": match.away_team, "home_total": match.home_total,
              "away_total": match.away_total, "result": match.result}
    existing = con.execute("SELECT file_id FROM match_files WHERE sha256 = ?", [raw.sha256]).fetchone()
    if existing is not None:
        return RecordedMatch(str(raw.path), match.giornata, True, int(existing[0]), True, 0, **common)
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO match_files (season_id, giornata, competition_id, matchday, fetched_at, raw_path, sha256, "
            "home_team, away_team, home_module, away_module, home_total, away_total, home_points, away_points, "
            "result, sign) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [season_id, match.giornata, match.competition_id, match.matchday, to_db(raw.fetched_at), str(raw.path),
             raw.sha256, match.home_team, match.away_team, match.home_module, match.away_module, match.home_total,
             match.away_total, match.home_points, match.away_points, match.result, match.sign]).fetchone()[0]
        con.executemany(
            "INSERT INTO match_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
            [[file_id, p.team_id, p.player_id, p.part, p.position, p.status, p.voto, p.fantavoto, p.malus, p.events,
              json.dumps(p.raw, ensure_ascii=False)] for p in match.players])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return RecordedMatch(str(raw.path), match.giornata, True, int(file_id), False, len(match.players), **common)


@dataclass(frozen=True)
class DiskSweep:
    files: list[RecordedMatch]
    before_season: int

    def to_dict(self) -> dict[str, Any]:
        return {"files": [f.to_dict() for f in self.files], "before_season": self.before_season,
                "recorded": sum(1 for f in self.files if f.calculated and not f.duplicate),
                "duplicates": sum(1 for f in self.files if f.duplicate),
                "not_calculated": sum(1 for f in self.files if not f.calculated)}


def record_from_disk(con: duckdb.DuckDBPyConnection, store: RawStore, *, season_id: int) -> DiskSweep:
    """Record the scores of every raw read-back already under data/raw/lineup/,
    no request made: the backlog, and `data/` rebuilt from `data/raw/`. A file
    fetched before the season's first Serie A kickoff cannot be this season's
    and is only counted. Never touches lineup_submitted -- the XI was recorded
    when the file was fetched."""
    first = con.execute("SELECT min(kickoff) FROM v_fixtures_current WHERE competition = 'SA' AND season_id = ?",
                        [season_id]).fetchone()[0]
    if first is None:
        raise NoSeasonCalendar(f"no Serie A calendar for season {season_id} -- run `fantaclaude ingest calendar`")
    files: list[RecordedMatch] = []
    before = 0
    for path in store.list("lineup"):
        raw = RawStore.on_disk(path, "lineup")
        if to_db(raw.fetched_at) < first:
            before += 1
            continue
        files.append(record_match(con, raw, json.loads(path.read_text(encoding="utf-8")), season_id=season_id))
    return DiskSweep(files, before)
