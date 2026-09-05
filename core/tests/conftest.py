import base64
import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
# The league API payload shapes are the MCP's ground truth; reuse its scrubbed
# fixtures instead of keeping a drifting second copy.
MCP_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "mcp" / "fantacalcio" / "tests" / "fixtures"


@pytest.fixture
def fixture_json():
    def _load(name: str):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def mcp_fixture_json():
    def _load(name: str):
        return json.loads((MCP_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def db(tmp_path):
    from fantaclaude.db.connection import connect
    from fantaclaude.db.schema import apply_schema

    con = connect(tmp_path / "test.duckdb")
    apply_schema(con)
    yield con
    con.close()


def make_jwt(**claims) -> str:
    """An unsigned RS256-shaped JWT with the given claims (test helper, mirrors the MCP suite)."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.signature"


class FakeAPI:
    """The subset of FantacalcioAPI the commands call, answered from fixtures.

    `overrides` replaces a named payload; `calls` records every method name
    so a test can assert how many round-trips a command made.
    """

    def __init__(self, load, overrides=None):
        self._load = load
        self._overrides = dict(overrides or {})
        self.calls: list[str] = []

    async def _answer(self, name: str):
        self.calls.append(name)
        if name in self._overrides:
            return json.loads(json.dumps(self._overrides[name]))
        return self._load(name)

    async def league_profile(self, league=None):
        return await self._answer("league_profile")

    async def league_status(self, league=None):
        return await self._answer("league_status")

    async def roster_settings(self, league=None):
        return await self._answer("roster_settings")

    async def lineup_settings(self, league=None):
        return await self._answer("lineup_settings")

    async def calculation_settings(self, league=None):
        return await self._answer("calculation_settings")

    async def teams(self, page=1, league=None):
        return await self._answer("teams")

    async def players(self, league=None):
        return await self._answer("players")


@pytest.fixture
def fake_api(mcp_fixture_json):
    def _make(overrides=None):
        return FakeAPI(mcp_fixture_json, overrides)
    return _make


@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / f"{name}.json"
    return _path


@pytest.fixture
def fixture_file():
    def _path(name: str) -> Path:
        return FIXTURE_DIR / name
    return _path


def seed_voti(con, season_id: int, giornata: int, rows, *, sheets=None) -> int:
    """One synthetic voti workbook -- one file, every sheet, as the real export is.
    `rows` are (player_id, name, team, classic_role, voto, events) for the Fantacalcio
    sheet, where voto None means senza voto and events is a dict of the workbook's
    count columns; `sheets` maps further sheet names to their own rows."""
    by_sheet = {"Fantacalcio": rows, **(sheets or {})}
    file_id = con.execute(
        "INSERT INTO voti_files (season_id, giornata, fetched_at, source, raw_path, sha256, sheets, row_count) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, ?) RETURNING file_id",
        [season_id, giornata, f"seed/{season_id}-{giornata}", f"seed-{season_id}-{giornata}", list(by_sheet),
         sum(len(r) for r in by_sheet.values())],
    ).fetchone()[0]
    for sheet, sheet_rows in by_sheet.items():
        for player_id, name, team, role, voto, events in sheet_rows:
            e = {"goals": 0, "goals_conceded": 0, "pen_saved": 0, "pen_missed": 0, "pen_scored": 0,
                 "own_goals": 0, "yellow": 0, "red": 0, "assists": 0, **(events or {})}
            con.execute(
                "INSERT INTO player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
                [file_id, season_id, giornata, sheet, player_id, name, team, role, voto, voto is None,
                 e["goals"], e["goals_conceded"], e["pen_saved"], e["pen_missed"], e["pen_scored"], e["own_goals"],
                 e["yellow"], e["red"], e["assists"]])
    return file_id


def seed_advanced(con, season_id: int, rows) -> int:
    """`rows` are (player_id, minutes, games, xg, xa); one matched Understat row each."""
    snapshot_id = con.execute(
        "INSERT INTO advanced_snapshots (season_id, fetched_at, source, raw_path, sha256, aliases_sha256, "
        "listone_snapshot_id, row_count, matched, ambiguous, unmatched) VALUES (?, now(), 'seed', ?, ?, 'seed', 1, ?, ?, 0, 0) "
        "RETURNING snapshot_id",
        [season_id, f"seed/adv-{season_id}", f"seed-adv-{season_id}", len(rows), len(rows)]).fetchone()[0]
    for player_id, minutes, games, xg, xa in rows:                     # npxg is seeded equal to xg
        con.execute(
            "INSERT INTO advanced_stats VALUES (?, ?, ?, ?, ?, ?, 'matched', [?], ?, ?, 0, 0, ?, ?, 0, ?, 0, 0, 0, 0, "
            "0.0, 0.0, 'F', '{}')",
            [snapshot_id, season_id, f"u{player_id}", f"p{player_id}", ["X"], player_id, player_id, games, minutes, xg, xa, xg])
    return snapshot_id


def seed_probabili(con, season_id: int, giornata: int, rows) -> int:
    """One synthetic probabili file. `rows` are (player_id, name, club_slug, p_start)
    or (player_id, name, club_slug, p_start, team_short)."""
    from uuid import uuid4
    file_id = con.execute(
        "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, uncompiled) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, 1, 0) RETURNING file_id",
        [season_id, giornata, f"seed/prob-{season_id}-{giornata}", f"seed-prob-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for row in rows:
        player_id, name, club, p_start = row[:4]
        short = row[4] if len(row) > 4 else None
        con.execute("INSERT INTO probabili VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, false, NULL, '{}')",
                    [file_id, season_id, giornata, player_id, name, club, short, p_start])
    return file_id


def seed_matches(con, season_id: int, rows) -> int:
    """One Serie A calendar snapshot with clubs. `rows` are (giornata, kickoff aware UTC, home_short, away_short)."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    snapshot_id = con.execute(
        "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
        "VALUES ('SA', ?, now(), 'seed', [], ?, ?) RETURNING snapshot_id",
        [season_id, f"seed-fix-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for i, (giornata, kickoff, home, away) in enumerate(rows):
        con.execute("INSERT INTO fixtures VALUES (?, 'SA', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '{}')",
                    [snapshot_id, season_id, f"seed-{giornata}-{i}", str(giornata), giornata, to_db(kickoff), home, away, home, away])
    return snapshot_id


def seed_news(con, season_id: int, giornata: int, page: str, rows) -> int:
    """One synthetic news file. `rows` are (kind, team_name, team_short, name, player_id, detail);
    a row with player_id None is written as unmatched."""
    from uuid import uuid4
    file_id = con.execute(
        "INSERT INTO news_files (kind, season_id, giornata, fetched_at, source, raw_path, sha256, row_count, teams, unmatched) "
        "VALUES (?, ?, ?, now(), 'seed', ?, ?, ?, 20, ?) RETURNING file_id",
        [page, season_id, giornata, f"seed/news-{page}-{season_id}-{giornata}", f"seed-news-{uuid4().hex[:8]}", len(rows),
         sum(1 for r in rows if r[4] is None)]).fetchone()[0]
    for position, (kind, team_name, team_short, name, player_id, detail) in enumerate(rows):
        con.execute("INSERT INTO unavailable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
                    [file_id, season_id, giornata, kind, team_name, team_short, name, player_id,
                     "matched" if player_id is not None else "unmatched", detail, position])
    return file_id


def seed_rosters(con, league_id: int, season_id: int, teams, *, matchday=None) -> int:
    """One roster snapshot. `teams` maps team_id -> (name, {player_id: cost})."""
    from uuid import uuid4
    rows = [(tid, name, pid, cost, i) for tid, (name, roster) in teams.items() for i, (pid, cost) in enumerate(roster.items())]
    team_list = [{"id": tid, "name": name, "owner": None, "size": len(roster)} for tid, (name, roster) in teams.items()]
    snapshot_id = con.execute(
        "INSERT INTO roster_snapshots (league_id, season_id, fetched_at, source, raw_path, sha256, matchday, matchday_start, "
        "team_count, teams, row_count) VALUES (?, ?, now(), 'seed', 'seed/rosters', ?, ?, NULL, ?, ?::JSON, ?) RETURNING snapshot_id",
        [league_id, season_id, f"seed-rosters-{uuid4().hex[:8]}", matchday, len(teams), json.dumps(team_list), len(rows)]).fetchone()[0]
    for tid, name, pid, cost, position in rows:
        con.execute("INSERT INTO rosters VALUES (?, ?, ?, NULL, ?, ?, ?)", [snapshot_id, tid, name, pid, cost, position])
    return snapshot_id


def seed_fixtures(con, season_id: int, rounds) -> int:
    """One Serie A calendar snapshot. `rounds` maps giornata -> list of kickoffs (aware UTC)."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    n = sum(len(k) for k in rounds.values())
    snapshot_id = con.execute(
        "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
        "VALUES ('SA', ?, now(), 'seed', [], ?, ?) RETURNING snapshot_id",
        [season_id, f"seed-fix-{uuid4().hex[:8]}", n]).fetchone()[0]
    for giornata, kickoffs in rounds.items():
        for i, kickoff in enumerate(kickoffs):
            con.execute("INSERT INTO fixtures VALUES (?, 'SA', ?, ?, ?, ?, NULL, ?, 'Home', 'Away', NULL, NULL, '{}')",
                        [snapshot_id, season_id, f"seed-{giornata}-{i}", str(giornata), giornata, to_db(kickoff)])
    return snapshot_id
