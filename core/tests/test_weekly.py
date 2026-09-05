from datetime import UTC, datetime, timedelta

import pytest
from conftest import seed_fixtures, seed_probabili, seed_rosters
from fantaclaude.analysis.weekly import (
    ADAPTED_MALUS,
    ForecastError,
    ForecastRow,
    LateForecast,
    RosterPlayer,
    Round,
    choose_xi,
    compilation_staleness,
    export_lineup_records,
    forecast,
    matchday_cross_check,
    my_roster,
    newest_probabili_file,
    target_round,
    write_lineup_run,
)
from fantaclaude.model.modules import load_modules
from fantaclaude.model.roles import Role

R = frozenset

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
G3 = [datetime(2026, 9, 4, 18, 45, tzinfo=UTC), datetime(2026, 9, 5, 16, 0, tzinfo=UTC), datetime(2026, 9, 7, 18, 45, tzinfo=UTC)]
G4 = [datetime(2026, 9, 11, 18, 45, tzinfo=UTC), datetime(2026, 9, 14, 18, 45, tzinfo=UTC)]


def _run(db, run_id="20260904T090510Z-7694bd6a", players=((2764, "Martinez L.", "INT", "A", ["Pc"], 8.1),
                                                         (5841, "Svilar", "ROM", "P", ["Por"], 5.6),
                                                         (2640, "Kolasinac", "ATA", "D", ["Ds", "Dc"], 6.0))):
    db.execute("INSERT INTO valuation_runs VALUES (?, ?, 'r', 'm3', 'i', 1, 1, 21, 2, ['balanced'], '{}', '{}')",
               [run_id, datetime(2026, 9, 4, 9, 5)])  # noqa: DTZ001 -- naive UTC, as stored
    for pid, name, short, role, roles, fm in players:
        db.execute("INSERT INTO valuations VALUES (?, ?, ?, ?, ?, ?, ?, 30.0, ?, 6.2, 10, 12, 14, 5.0, 7.0, 1, 20, NULL, NULL, '{}')",
                   [run_id, pid, name, short, role, roles[0], roles, fm])
    return run_id


def test_target_round_is_the_first_giornata_whose_last_kickoff_is_ahead(db):
    seed_fixtures(db, 21, {3: G3, 4: G4})
    r = target_round(db, NOW, season_id=21)
    assert r == Round(21, 3, datetime(2026, 9, 4, 18, 45), datetime(2026, 9, 7, 18, 45), 3)  # noqa: DTZ001 -- naive UTC, as fixtures stores it
    assert target_round(db, datetime(2026, 9, 5, 10, 0, tzinfo=UTC), season_id=21).giornata == 3   # in progress: still 3
    assert target_round(db, datetime(2026, 9, 8, 10, 0, tzinfo=UTC), season_id=21).giornata == 4
    assert target_round(db, NOW, season_id=21, giornata=4).giornata == 4
    with pytest.raises(ForecastError, match="giornata 9"):
        target_round(db, NOW, season_id=21, giornata=9)
    with pytest.raises(ForecastError, match="kicked off"):
        target_round(db, datetime(2026, 9, 20, tzinfo=UTC), season_id=21)


def test_target_round_needs_a_calendar(db):
    with pytest.raises(ForecastError, match="ingest calendar"):
        target_round(db, NOW, season_id=21)


def test_forecast_joins_the_page_to_the_run_for_every_listed_priced_player(db):
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90), (5841, "Svilar", "roma", 55), (777777, "Nobody", "roma", 5)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id).rows
    assert [r.player_id for r in rows] == [2764, 5841]                # the unpriced id is not a row; Kolasinac unlisted is not a row
    lautaro = rows[0]
    assert lautaro.p_start_published == 90 and lautaro.p_start == pytest.approx(0.9)
    assert lautaro.fv_if_plays == pytest.approx(8.1) and lautaro.expected_points == pytest.approx(0.9 * 8.1)
    assert lautaro.fv_sd is None and lautaro.source == "published" and lautaro.roles == ("Pc",)
    assert newest_probabili_file(db, 21, 3)[0] == file_id and newest_probabili_file(db, 21, 4) is None


def test_write_refuses_only_after_the_last_kickoff_unless_late_and_marks_the_row(db, tmp_path):
    """3b: the XI is late once the round's first kickoff has passed, but the
    write itself is refused only once EVERY match of the round has kicked
    off (open question 18) -- unlike 3a, a write between the first and the
    last kickoff succeeds and is simply marked late."""
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id).rows
    r = target_round(db, NOW, season_id=21)
    first, first_late = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    assert first_late is False
    between = datetime(2026, 9, 4, 19, 0, tzinfo=UTC)                        # past the first kickoff, well before the last (7 Sept)
    second, second_late = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=between, late=False)
    assert second != first and second_late is True
    assert db.execute("SELECT late, deadline FROM lineup_runs ORDER BY lineup_run_id").fetchall() == \
        [(False, datetime(2026, 9, 4, 18, 45)), (True, datetime(2026, 9, 4, 18, 45))]  # noqa: DTZ001 -- naive UTC, as stored
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(first,)]
    assert db.execute("SELECT p_start_published, p_start, expected_points, source FROM predictions WHERE lineup_run_id = ?",
                      [first]).fetchone() == (90, pytest.approx(0.9), pytest.approx(0.9 * 8.1), "published")
    after_last = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)                     # past every kickoff of the round
    with pytest.raises(LateForecast, match="--late"):
        write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after_last, late=False)
    third, third_late = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=after_last, late=True)
    assert third != second and third_late is True
    # --late before the deadline is not late: the flag permits, the clock decides
    fourth, fourth_late = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=True)
    assert fourth_late is False
    assert db.execute("SELECT late FROM lineup_runs WHERE lineup_run_id = ?", [fourth]).fetchone() == (False,)
    assert db.execute("SELECT lineup_run_id FROM v_lineup_runs_current").fetchall() == [(fourth,)]


def test_a_second_run_before_the_deadline_is_a_second_row_and_nothing_is_touched(db):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id).rows
    r = target_round(db, NOW, season_id=21)
    a, _ = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    b, _ = write_lineup_run(db, round_=r, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW + timedelta(hours=1), late=False)
    assert db.execute("SELECT count(*) FROM lineup_runs").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM predictions").fetchone()[0] == 2
    assert db.execute("SELECT written_at FROM lineup_runs WHERE lineup_run_id = ?", [a]).fetchone()[0] == \
        datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 -- naive UTC, as stored
    assert b > a


def test_write_refuses_an_empty_forecast(db):
    seed_fixtures(db, 21, {3: G3})
    r = target_round(db, NOW, season_id=21)
    with pytest.raises(ForecastError, match="nothing to forecast"):
        write_lineup_run(db, round_=r, run_id="x", model_hash="m", probabili_file_id=1, rows=[], now=NOW, late=False)


def test_records_are_exported_once_by_giornata_and_write_time(db, tmp_path):
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id).rows
    lineup_run_id, _ = write_lineup_run(db, round_=target_round(db, NOW, season_id=21), run_id=run_id, model_hash="m3",
                                        probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    written = export_lineup_records(db, lineup_run_id, tmp_path / "records")
    assert [p.relative_to(tmp_path / "records").as_posix() for p in written] == \
        [f"lineup_runs/21-03-20260904T120000Z-{lineup_run_id}.parquet",
         f"predictions/21-03-20260904T120000Z-{lineup_run_id}.parquet"]
    assert export_lineup_records(db, lineup_run_id, tmp_path / "records") == []          # never rewritten
    assert db.execute("SELECT count(*) FROM read_parquet(?)", [str(written[1])]).fetchone()[0] == 1


def test_two_runs_in_the_same_second_each_get_their_own_permanent_record(db, tmp_path):
    """`written_at` is second-precision in the stem; two `lineup` invocations
    in the same second are two immutable `lineup_runs` rows and must be two
    parquet pairs, not one silently skipped as `write_parquet` reads as
    "records already exist" (review finding 3, 2026-09-04)."""
    seed_fixtures(db, 21, {3: G3})
    run_id = _run(db)
    file_id = seed_probabili(db, 21, 3, [(2764, "Martinez L.", "inter", 90)])
    rows = forecast(db, run_id=run_id, probabili_file_id=file_id).rows
    round_ = target_round(db, NOW, season_id=21)
    a, _ = write_lineup_run(db, round_=round_, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    b, _ = write_lineup_run(db, round_=round_, run_id=run_id, model_hash="m3", probabili_file_id=file_id, rows=rows, now=NOW, late=False)
    assert a != b
    assert db.execute("SELECT written_at FROM lineup_runs WHERE lineup_run_id IN (?, ?)", [a, b]).fetchall() == \
        [(datetime(2026, 9, 4, 12, 0),), (datetime(2026, 9, 4, 12, 0),)]  # noqa: DTZ001 -- naive UTC, as stored -- same second
    written_a = export_lineup_records(db, a, tmp_path / "records")
    written_b = export_lineup_records(db, b, tmp_path / "records")
    assert written_a and written_b                       # neither is skipped as "already exists"
    assert {p.name for p in written_a}.isdisjoint(p.name for p in written_b)
    assert db.execute("SELECT count(*) FROM read_parquet(?)", [str(written_b[1])]).fetchone()[0] == 1


def _row(pid, role, p, fv):
    return ForecastRow(pid, f"p{pid}", None, role, (), int(p * 100), p, fv, None, p * fv, "published")


def test_choose_xi_takes_the_best_module_and_scores_every_permitted_one():
    modules = load_modules()
    roles = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}), R({Role.C}),
             R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A}), R({Role.Dd})]
    roster = [RosterPlayer(100 + i, f"p{100 + i}", r, 1, True) for i, r in enumerate(roles)]
    forecast = {p.player_id: _row(p.player_id, "C", 0.9, 6.0) for p in roster}
    forecast[111] = _row(111, "D", 1.0, 8.0)                  # the Dd: worth 8 natural, 8 - 1.0 adapted at E
    choice = choose_xi(roster, forecast, modules, ["343", "442"])
    assert set(choice.module_scores) == {"343", "442"}
    assert choice.module in {"343", "442"} and choice.total == pytest.approx(max(v for v in choice.module_scores.values() if v is not None))
    assert len(choice.slots) == 11 and len({s.player_id for s in choice.slots}) == 11
    assert choice.unlisted == []
    fielded = {s.player_id: s for s in choice.slots}
    if 111 in fielded:
        assert fielded[111].fit == "adapted" and fielded[111].expected_points == pytest.approx(8.0 - 1.0 * ADAPTED_MALUS)


def test_choose_xi_counts_an_unlisted_player_as_zero_and_says_so():
    modules = load_modules()
    roles = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}), R({Role.C}),
             R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    roster = [RosterPlayer(200 + i, f"p{200 + i}", r, 1, True) for i, r in enumerate(roles)]
    forecast = {p.player_id: _row(p.player_id, "C", 0.9, 6.0) for p in roster[:-1]}    # the A is not on the page
    choice = choose_xi(roster, forecast, modules, ["343"])
    assert choice.unlisted == [210] and choice.module == "343"
    assert next(s for s in choice.slots if s.player_id == 210).expected_points == 0.0


def test_choose_xi_refuses_when_no_permitted_module_can_be_fielded():
    modules = load_modules()
    roster = [RosterPlayer(i, f"p{i}", R({Role.Dc}), 1, True) for i in range(12)]
    with pytest.raises(ForecastError, match="no permitted module"):
        choose_xi(roster, {}, modules, ["343"])
    with pytest.raises(ForecastError, match="not in modules.yml"):
        choose_xi(roster, {}, modules, ["999"])


def test_my_roster_reads_the_latest_snapshot_and_keeps_an_id_the_listone_lacks(db):
    db.execute("INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) VALUES (now(), 'seed', 'seed', 'seed', 1)")
    db.execute("INSERT INTO players VALUES (1, 2764, 'Martinez L.', 1, 'Inter', 'INT', 'A', ['Pc'], [16], 30, 30, 40, 40, 100, 100, 29, 'ARG', false, '{}')")
    seed_rosters(db, 1, 21, {10: ("Mine", {2764: 120, 795: 1})})
    roster = my_roster(db, 10)
    assert [(p.player_id, p.name, p.roles, p.cost, p.in_listone) for p in roster] == \
        [(2764, "Martinez L.", R({Role.Pc}), 120, True), (795, "#795", R(), 1, False)]
    with pytest.raises(ForecastError, match="ingest rosters"):
        my_roster(db, 11)


def test_the_platforms_matchday_is_a_cross_check_on_the_calendar(db):
    seed_fixtures(db, 21, {3: G3})
    r = target_round(db, NOW, season_id=21)
    assert matchday_cross_check(db, r) is None                                   # nothing fetched yet
    seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=3)
    db.execute("UPDATE roster_snapshots SET matchday_start = ? WHERE matchday = 3", [datetime(2026, 9, 4, 18, 45)])  # noqa: DTZ001 -- naive UTC, as stored
    assert matchday_cross_check(db, r) is None                                   # agrees
    seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=4)
    assert "matchday 4" in matchday_cross_check(db, r)                           # the platform moved on


def test_a_stale_matchday_read_is_silent_but_a_current_disagreement_still_warns(db):
    """`ingest rosters` runs "when the rosters changed, never to check", so
    the freshest snapshot can sit for weeks after its own giornata passed --
    matchday 3, fetched the day after the auction, must not be compared
    against giornata 4's calendar a week later and beyond (review finding 4,
    2026-09-04). A snapshot fetched close to the round being checked, even
    if it disagrees, must still warn -- the gate is about the READ's age,
    not about disagreement being tolerated."""
    from fantaclaude.timeutil import to_db

    seed_fixtures(db, 21, {3: G3, 4: G4})
    r3 = target_round(db, NOW, season_id=21, giornata=3)
    r4 = target_round(db, NOW, season_id=21, giornata=4)
    snap = seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=3)
    db.execute("UPDATE roster_snapshots SET matchday_start = ?, fetched_at = ? WHERE snapshot_id = ?",
              [to_db(G3[0]), to_db(datetime(2026, 9, 4, 13, 46, tzinfo=UTC)), snap])
    assert matchday_cross_check(db, r3) is None                                  # still within its own round's window
    assert matchday_cross_check(db, r4) is None                                  # a week stale for giornata 4: silent
    fresh = seed_rosters(db, 1, 21, {10: ("Mine", {})}, matchday=3)
    db.execute("UPDATE roster_snapshots SET fetched_at = ? WHERE snapshot_id = ?",
              [to_db(G4[0] - timedelta(days=1)), fresh])
    assert "matchday 3" in matchday_cross_check(db, r4)                          # recent AND disagreeing: still warns


def _seed_fixtures_with_shorts(con, season_id, giornata, matches):
    """`matches`: (home_short, away_short, kickoff aware UTC). Unlike
    `seed_fixtures`, this fills `home_short`/`away_short` -- the listone
    short code `compilation_staleness` joins probabili's `team_short` on."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    snapshot_id = con.execute(
        "INSERT INTO fixture_snapshots (competition, season_id, fetched_at, source, raw_paths, sha256, row_count) "
        "VALUES ('SA', ?, now(), 'seed', [], ?, ?) RETURNING snapshot_id",
        [season_id, f"seed-fix-shorts-{uuid4().hex[:8]}", len(matches)]).fetchone()[0]
    for i, (home_short, away_short, kickoff) in enumerate(matches):
        con.execute("INSERT INTO fixtures VALUES (?, 'SA', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '{}')",
                    [snapshot_id, season_id, f"seed-shorts-{giornata}-{i}", str(giornata), giornata,
                     to_db(kickoff), home_short, away_short, home_short, away_short])
    return snapshot_id


def _seed_probabili_with_team(con, season_id, giornata, rows):
    """`rows`: (player_id, team_short or None, updated_at aware UTC or None).
    Unlike `seed_probabili`, this fills `team_short` and `updated_at` directly
    -- `compilation_staleness` reads both."""
    from uuid import uuid4

    from fantaclaude.timeutil import to_db
    file_id = con.execute(
        "INSERT INTO probabili_files (season_id, giornata, fetched_at, source, raw_path, sha256, row_count, matches, uncompiled) "
        "VALUES (?, ?, now(), 'seed', ?, ?, ?, 1, 0) RETURNING file_id",
        [season_id, giornata, f"seed/prob-team-{season_id}-{giornata}",
         f"seed-prob-team-{uuid4().hex[:8]}", len(rows)]).fetchone()[0]
    for player_id, team_short, updated_at in rows:
        con.execute("INSERT INTO probabili VALUES (?, ?, ?, ?, ?, 'slug', ?, NULL, 90, false, ?, '{}')",
                    [file_id, season_id, giornata, player_id, f"p{player_id}", team_short,
                     to_db(updated_at) if updated_at else None])
    return file_id


def test_compilation_staleness_warns_per_match_against_its_own_kickoff(db):
    """The join is on `team_short` -- the listone short code `ingest
    probabili` already resolves per player from `player_id` (the reliable
    join the page gives for free), and the same listone fills
    `fixtures.home_short`/`away_short` at calendar ingest -- so the two
    columns already speak one vocabulary. `club_slug`, the fantacalcio.it
    URL slug, has no such mapping anywhere in this codebase and is not one
    to invent here (review finding 2, 2026-09-04)."""
    _seed_fixtures_with_shorts(db, 21, 3, [
        ("INT", "ROM", datetime(2026, 9, 6, 18, 0, tzinfo=UTC)),      # compiled 4+ days before its own kickoff: stale
        ("JUV", "MIL", datetime(2026, 9, 7, 20, 45, tzinfo=UTC)),     # compiled hours before its own kickoff: not stale
    ])
    file_id = _seed_probabili_with_team(db, 21, 3, [
        (1, "INT", datetime(2026, 9, 2, 10, 0, tzinfo=UTC)),
        (2, "ROM", datetime(2026, 9, 2, 10, 0, tzinfo=UTC)),
        (3, "JUV", datetime(2026, 9, 7, 10, 0, tzinfo=UTC)),
        (4, "MIL", datetime(2026, 9, 7, 10, 0, tzinfo=UTC)),
        (5, None, datetime(2026, 9, 1, 0, 0, tzinfo=UTC)),            # no listone club: not checked, not a crash
    ])
    warnings = compilation_staleness(db, 3, file_id)
    assert len(warnings) == 1
    assert "INT-ROM" in warnings[0] and "4 day" in warnings[0] and "stale" in warnings[0]
    assert "JUV" not in warnings[0] and "MIL" not in warnings[0]


def test_compilation_staleness_is_silent_with_nothing_to_join_or_nothing_stale(db):
    # no fixtures at all for this giornata: the join finds nothing, no crash
    file_id = _seed_probabili_with_team(db, 21, 4, [(1, "INT", datetime(2026, 9, 2, 10, 0, tzinfo=UTC))])
    assert compilation_staleness(db, 4, file_id) == []
    # a fixture exists but compiled well within a day of its own kickoff: not stale
    _seed_fixtures_with_shorts(db, 21, 5, [("INT", "ROM", datetime(2026, 9, 13, 15, 0, tzinfo=UTC))])
    fresh = _seed_probabili_with_team(db, 21, 5, [(1, "INT", datetime(2026, 9, 13, 9, 0, tzinfo=UTC))])
    assert compilation_staleness(db, 5, fresh) == []


def test_lineup_surfaces_the_staleness_warning(db, tmp_path):
    """End-to-end: `lineup` wires `compilation_staleness` into its own
    warnings, the way `matchday_cross_check` and the uncompiled-match count
    already are."""
    from fantaclaude.analysis.weekly import lineup
    run_id = _run(db)                                       # prices 2764 (INT), among others
    _seed_fixtures_with_shorts(db, 21, 3, [
        ("INT", "ROM", NOW + timedelta(days=2)),
        ("JUV", "MIL", NOW + timedelta(days=3)),
    ])
    _seed_probabili_with_team(db, 21, 3, [
        (2764, "INT", NOW - timedelta(days=6)),                          # stale: priced AND on the page
        (999901, "ROM", NOW - timedelta(days=6)),
        (999902, "JUV", NOW + timedelta(days=3) - timedelta(hours=2)),   # not stale: hours before ITS OWN kickoff
        (999903, "MIL", NOW + timedelta(days=3) - timedelta(hours=2)),
    ])
    report = lineup(db, now=NOW, season_id=21, giornata=None, run_id=run_id, late=False, my_team=None,
                    records_dir=tmp_path / "records")
    assert any("INT-ROM" in w and "stale" in w for w in report.warnings)
    assert not any("JUV" in w or "MIL" in w for w in report.warnings)
