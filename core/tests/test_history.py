import pytest
from conftest import seed_advanced, seed_voti
from fantaclaude.analysis.history import History, RolePrior, SeasonLine, load_history
from fantaclaude.model.scoring import BonusMalus, Events


@pytest.fixture
def bm(mcp_fixture_json):
    return BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))


def _seed(db):
    # season 20: giornate 1-3 exist; Lautaro (2764) plays two, one senza voto; a goalkeeper; a coach row to ignore
    seed_voti(db, 20, 1, [(2764, "Martinez L.", "Inter", "A", 7.0, {"goals": 1, "pen_scored": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 2}),
                          (688, "Sarri", "Atalanta", "ALL", 6.0, {}),
                          (2640, "Kolasinac", "Atalanta", "D", 6.0, {"yellow": 1})])
    seed_voti(db, 20, 2, [(2764, "Martinez L.", "Inter", "A", 6.0, {"assists": 1}),
                          (5841, "Svilar", "Roma", "P", 6.5, {"pen_saved": 1}),
                          (2640, "Kolasinac", "Atalanta", "D", 5.5, {"pen_missed": 1})])
    seed_voti(db, 20, 3, [(2764, "Martinez L.", "Inter", "A", None, {}),
                          (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 1}),
                          (9999, "Riserva", "Lazio", "C", None, {})])       # never voted: a zero-presenze season
    # season 21: one giornata played; the workbook's other sheet must not leak in
    seed_voti(db, 21, 1, [(2764, "Martinez L.", "Inter", "A", 6.5, {"goals": 1}),
                          (5841, "Svilar", "Roma", "P", 6.0, {})],
              sheets={"Italia": [(2764, "Martinez L.", "Inter", "A", 9.0, {"goals": 3})]})
    seed_advanced(db, 20, [(2764, 170, 2, 1.4, 0.3)])


def test_load_history_builds_season_lines_under_the_league_scoring(db, bm):
    _seed(db)
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21, back=3)
    assert isinstance(history, History) and history.sheet == "Fantacalcio"
    assert history.seasons == (18, 19, 20, 21) and history.giornate == {20: 3, 21: 1}
    assert history.giornate_played == 1

    lines = history.lines_for(2764)
    assert [line.season_id for line in lines] == [21, 20]                       # newest first
    s20 = lines[1]
    assert isinstance(s20, SeasonLine)
    assert (s20.team, s20.classic_role, s20.appearances, s20.presenze, s20.giornate) == ("Inter", "A", 3, 2, 3)
    assert s20.voto_mean == pytest.approx(6.5)
    assert s20.events == Events(goals=1, pen_scored=1, assists=1)
    # fantavoti: 7 + 3 + 3 = 13 and 6 + 1 = 7 -> mean 10, population variance 9
    assert s20.fantavoto_mean == pytest.approx(10.0) and s20.fantavoto_var == pytest.approx(9.0)
    assert (s20.minutes, s20.understat_games, s20.xg, s20.xa, s20.npxg) == (170, 2, pytest.approx(1.4), pytest.approx(0.3), pytest.approx(1.4))
    s21 = lines[0]
    assert (s21.presenze, s21.giornate, s21.fantavoto_mean, s21.minutes) == (1, 1, pytest.approx(9.5), None)
    assert s21.fantavoto_var == pytest.approx(0.0)                          # a single observation, not undefined

    keeper = history.lines_for(5841)[1]
    assert keeper.events == Events(goals_conceded=3, pen_saved=1)
    assert keeper.fantavoto_mean == pytest.approx(((6 - 2) + (6.5 + 3) + (6 - 1)) / 3)
    assert history.lines_for(688) == () and history.lines_for(999) == ()      # the coach row is not a player

    never_voted = history.lines_for(9999)[0]                                 # senza-voto only: zero presenze
    assert never_voted.presenze == 0 and never_voted.appearances == 1
    assert (never_voted.voto_mean, never_voted.fantavoto_mean, never_voted.fantavoto_var) == (0.0, 0.0, 0.0)


def test_role_priors_and_club_penalties_come_from_the_back_seasons(db, bm):
    _seed(db)
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21, back=3)
    prior = history.priors["A"]
    assert isinstance(prior, RolePrior)
    assert prior.rows == 2 and prior.fantavoto_mean == pytest.approx(10.0) and prior.fantavoto_sd == pytest.approx(3.0)
    assert prior.voto_mean == pytest.approx(6.5)
    assert prior.presenze_rate == pytest.approx(2 / 3)                          # Lautaro: 2 voti in 3 giornate
    assert history.priors["D"].fantavoto_mean == pytest.approx(((6 - 0.5) + (5.5 - 2)) / 2)
    assert "ALL" not in history.priors and "C" not in history.priors           # no rows, no prior
    assert history.club_penalty_rate == {"Inter": pytest.approx(1 / 3), "Atalanta": pytest.approx(1 / 3)}
    # penalty_rate() tells "played and took none" from "never named at all":
    # the projection redistributes on the first and must not act on the second
    # (finding A -- Frosinone, Monza and Venezia have no back season here).
    assert history.penalty_rate("Inter") == pytest.approx(1 / 3)
    assert history.penalty_rate("Roma") == 0.0                                # in the season, took no penalty
    assert history.penalty_rate("Venezia") is None                            # never played it


def test_an_empty_history_is_empty_not_broken(db, bm):
    history = load_history(db, sheet="Fantacalcio", bm=bm, current_season=21)
    assert history.lines_for(2764) == () and history.priors == {} and history.giornate_played == 0


def test_event_columns_are_real_columns_of_the_view_the_query_interpolates_them_into(db):
    """load_history's SELECT interpolates EVENT_COLUMNS by name into
    v_player_match_current (history.py:112), unchecked by the SQL parser
    until the query runs. A name in EVENT_COLUMNS the view does not have
    would be a duckdb.Error at that query, not at import -- this is the
    guard for that, not a restatement of history.py's own derivation."""
    from fantaclaude.analysis.history import EVENT_COLUMNS

    columns = {row[0] for row in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'v_player_match_current'").fetchall()}
    assert set(EVENT_COLUMNS) <= columns
