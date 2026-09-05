from datetime import UTC, datetime

import pytest
from conftest import seed_matches, seed_voti
from fantaclaude.analysis.weekly.config import WeeklyConfig
from fantaclaude.analysis.weekly.forecast import (
    Terms,
    load_matchups,
    load_spreads,
    load_terms,
    matchup_term,
    spread_for,
)
from fantaclaude.analysis.weekly.rounds import PlayerFixture
from fantaclaude.model.scoring import BonusMalus

BM = BonusMalus(goal=3, penalty_goal=3, assist=1, goal_conceded=-1, penalty_saved=3, penalty_missed=-3, yellow=-0.5, red=-1, own_goal=-2)
CFG = WeeklyConfig(matchup_shrink_k=2.0, matchup_cap=1.0, spread_prior_k=2.0)
KO = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)


def _teams(db):
    db.execute("INSERT INTO listone_snapshots (fetched_at, source, raw_path, sha256, player_count) VALUES (now(), 'seed', 'x', 'seed-teams', 0)")
    sid = db.execute("SELECT max(snapshot_id) FROM listone_snapshots").fetchone()[0]
    for tid, name, short in ((1, "Inter", "INT"), (2, "Roma", "ROM"), (3, "Atalanta", "ATA"), (4, "Genoa", "GEN")):
        db.execute("INSERT INTO teams VALUES (?, ?, ?, ?)", [sid, tid, name, short])


def _season(db):
    _teams(db)
    # giornata 1: Inter home to Roma, Atalanta home to Genoa; giornata 2: Roma home to Atalanta, Genoa home to Inter
    seed_matches(db, 21, [(1, KO, "INT", "ROM"), (1, KO, "ATA", "GEN"), (2, KO, "ROM", "ATA"), (2, KO, "GEN", "INT")])
    seed_voti(db, 21, 1, [(1, "a", "Inter", "A", 7.0, {}), (2, "b", "Roma", "A", 5.0, {}), (3, "c", "Atalanta", "D", 6.0, {}),
                          (4, "d", "Inter", "D", 6.0, {})])
    seed_voti(db, 21, 2, [(1, "a", "Inter", "A", 6.0, {}), (2, "b", "Roma", "A", 6.0, {}), (3, "c", "Atalanta", "D", 5.0, {}),
                          (4, "d", "Inter", "D", 7.0, {}), (5, "e", "Roma", "A", None, {})])


def test_matchups_read_this_seasons_rows_and_shrink_toward_zero(db):
    _season(db)
    table = load_matchups(db, season_id=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    assert table.rows == 8 and table.season_id == 21                                    # the senza voto row is not a rating
    # attackers: Inter home 7.0 (g1), Roma home 6.0 (g2); Roma away 5.0 (g1), Inter away 6.0 (g2): role mean 6.0
    delta, n = table.venue[("A", True)]
    assert n == 2 and delta == pytest.approx((6.5 - 6.0) * 2 / (2 + 2.0))                 # shrunk by n / (n + k)
    # conceded to attackers by Roma: the attackers who faced Roma (Inter's a, g1, 7.0) against the role mean 6.0
    delta, n = table.conceded[("ROM", "A")]
    assert n == 1 and delta == pytest.approx((7.0 - 6.0) * 1 / 3)
    assert table.conceded[("GEN", "A")] == (pytest.approx(0.0), 1)                        # Inter's a, g2, 6.0: at the mean


def test_the_term_is_the_two_shrunk_deltas_capped_and_traced(db):
    _season(db)
    table = load_matchups(db, season_id=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    term, trace = matchup_term(table, classic_role="A", fixture=PlayerFixture(KO.replace(tzinfo=None), True, "ROM"), cfg=CFG)
    assert term == pytest.approx(table.venue[("A", True)][0] + table.conceded[("ROM", "A")][0])
    assert trace["home"] is True and trace["opponent"] == "ROM" and trace["n_venue"] == 2 and trace["n_conceded"] == 1
    capped, _ = matchup_term(table, classic_role="A", fixture=PlayerFixture(KO.replace(tzinfo=None), True, "ROM"),
                             cfg=WeeklyConfig(matchup_cap=0.1))
    assert capped == pytest.approx(0.1)                                                     # 0.25 + 0.33 held at the cap
    nothing, trace = matchup_term(table, classic_role="A", fixture=None, cfg=CFG)
    assert nothing == 0.0 and trace == {"reason": "no fixture"}
    unknown, trace = matchup_term(table, classic_role="P", fixture=PlayerFixture(KO.replace(tzinfo=None), False, "XXX"), cfg=CFG)
    assert unknown == 0.0 and trace["n_venue"] == 0 and trace["n_conceded"] == 0


def test_spreads_pool_the_players_own_dispersion_with_the_role_prior(db):
    _teams(db)
    for g, votes in enumerate(((6.0, 5.0), (8.0, 5.0), (7.0, 5.0)), start=1):                   # back season 20: a swings, b is flat
        seed_voti(db, 20, g, [(1, "a", "Inter", "A", votes[0], {}), (2, "b", "Roma", "A", votes[1], {})])
    seed_voti(db, 21, 1, [(1, "a", "Inter", "A", 6.5, {}), (3, "c", "Atalanta", "A", 6.0, {})])
    table = load_spreads(db, current_season=21, sheet="Fantacalcio", bm=BM, cfg=CFG)
    prior = table.role_prior["A"]
    assert prior == pytest.approx((sum((v - 6.0) ** 2 for v in (6.0, 8.0, 7.0, 5.0, 5.0, 5.0)) / 6) ** 0.5)  # pstdev of the back rows
    own, n = table.player[1]
    assert n == 4
    sd, trace = spread_for(table, player_id=1, classic_role="A", cfg=CFG)
    assert sd == pytest.approx(((n * own ** 2 + 2.0 * prior ** 2) / (n + 2.0)) ** 0.5) and trace["n"] == 4
    thin, trace = spread_for(table, player_id=3, classic_role="A", cfg=CFG)                        # one rating: the prior nearly alone
    assert trace["n"] == 1 and thin == pytest.approx(((1 * 0.0 + 2.0 * prior ** 2) / 3.0) ** 0.5)
    none, trace = spread_for(table, player_id=99, classic_role="A", cfg=CFG)
    assert none == pytest.approx(prior) and trace["n"] == 0
    missing, trace = spread_for(table, player_id=1, classic_role="X", cfg=CFG)
    assert missing is None and trace == {"reason": "no role prior"}


def test_load_terms_reads_the_scoring_in_force(db, mcp_fixture_json):
    from fantaclaude.league.settings import record_snapshot, snapshot_from_payloads
    record_snapshot(db, snapshot_from_payloads(
        profile=mcp_fixture_json("league_profile"), status=mcp_fixture_json("league_status"),
        rosters=mcp_fixture_json("roster_settings"), lineup=mcp_fixture_json("lineup_settings"),
        calculate=mcp_fixture_json("calculation_settings"), teams=mcp_fixture_json("teams")))
    terms = load_terms(db, season_id=21, cfg=CFG)
    assert isinstance(terms, Terms) and terms.matchups.rows == 0 and terms.spreads.role_prior == {}
