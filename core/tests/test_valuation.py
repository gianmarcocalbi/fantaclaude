import json
from datetime import UTC, datetime

import duckdb
import pytest
from conftest import seed_voti
from fantaclaude.analysis.projection import ProjectionConfig
from fantaclaude.analysis.valuation import (
    MODEL_VERSION,
    PreferencesError,
    Scenario,
    UnknownScenarioError,
    ValuationError,
    ValuationRun,
    assign_tiers,
    divergence,
    inputs_hash,
    load_scenarios,
    model_hash,
    new_run_id,
    record_run,
    replacement_levels,
    run_valuation,
)
from fantaclaude.asta.pricing import NEG, PoolPlayer, PricingConfig
from fantaclaude.db.connection import connect
from fantaclaude.kb.notes import load_player_notes
from fantaclaude.kb.profiles import load_profiles
from fantaclaude.model.d_factor import load_d_factor
from test_doctor import _ready_workspace
from test_kb_profiles import _write as write_profile

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
PREFS = {"risk_appetite": "balanced", "max_budget_share_per_role": {}, "excluded_clubs": [],
         "target_composition": {"Por": 2}}


def seeded(tmp_path, fixture_json, mcp_fixture_json, *, profiles=True, rows20=None, penalties="Calhanoglu"):
    """The doctor's ready workspace plus profiles for its 8 clubs and a back season for a few players."""
    _ready_workspace(tmp_path, fixture_json, mcp_fixture_json)
    kb = tmp_path / "kb"
    if profiles:
        for name, short in (("Cagliari", "CAG"), ("Roma", "ROM"), ("Inter", "INT"), ("Milan", "MIL"), ("Fiorentina", "FIO"),
                            ("Napoli", "NAP"), ("Genoa", "GEN")):
            write_profile(kb, name, short, europe="none", rotation="1.0", penalties=penalties)
        write_profile(kb, "Atalanta", "ATA", europe="UECL", rotation="0.85", penalties=penalties)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    rows20 = rows20 or [(2764, "Martinez L.", "Inter", "A", 6.5, {"goals": 1}), (6052, "Hojlund", "Napoli", "A", 6.0, {}),
                        (2120, "Bastoni", "Inter", "D", 6.5, {}), (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 1}),
                        (152, "Barella", "Inter", "C", 6.5, {"assists": 1}), (2423, "Pulisic", "Milan", "A", 7.0, {"goals": 1})]
    for giornata in range(1, 31):
        seed_voti(con, 20, giornata, rows20)
    con.close()
    return tmp_path


def run(tmp_path, **kw):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        kw.setdefault("now", NOW)
        kw.setdefault("kb_dir", tmp_path / "kb")
        kw.setdefault("preferences", PREFS)
        kw.setdefault("projection_cfg", ProjectionConfig())
        kw.setdefault("pricing_cfg", PricingConfig())
        kw.setdefault("d_factor", load_d_factor())
        return run_valuation(con, **kw), con
    except Exception:
        con.close()
        raise


def test_scenarios_come_from_preferences_with_balanced_first():
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"target_composition": {"A": 2, "Pc": 2}, "risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    scenarios = load_scenarios(prefs)
    assert [s.name for s in scenarios] == ["balanced", "aggressive-attack", "value-hunting"]
    assert scenarios[0] == Scenario("balanced", {"Por": 2}, "balanced", {})
    assert scenarios[1].target_composition == {"Por": 2, "A": 2, "Pc": 2} and scenarios[1].quantile == "p75"
    assert scenarios[2].max_budget_share_per_role == {"Pc": 0.25} and scenarios[2].quantile == "p25"
    assert load_scenarios(PREFS) == [scenarios[0]]
    for bad in ({**PREFS, "risk_appetite": "wild"}, {**PREFS, "target_composition": {"Xy": 1}},
                {**PREFS, "scenarios": {"x": {"max_budget_share_per_role": {"Pc": 3}}}}, {**PREFS, "scenarios": [1]}):
        with pytest.raises(PreferencesError):
            load_scenarios(bad)


def test_a_balanced_scenario_block_is_refused_not_silently_dropped():
    """Finding 9. Every other malformed scenario raises, but a block named
    after the base one was skipped: `scenarios.balanced.risk_appetite:
    cautious` never applied, the ignored block still landed in config and in
    model_hash, and the asta plan still said "bid to p50" under a heading the
    operator had just told to be cautious. Refusing keeps one place to say
    what balanced is -- the file's own top-level keys -- rather than two with
    a precedence rule nobody can see."""
    prefs = {**PREFS, "scenarios": {"balanced": {"risk_appetite": "cautious"}}}
    with pytest.raises(PreferencesError, match="balanced"):
        load_scenarios(prefs)
    with pytest.raises(PreferencesError, match="balanced"):
        load_scenarios({**PREFS, "scenarios": {"balanced": {}}})
    # the top-level keys are how balanced is configured, and they still work
    assert load_scenarios({**PREFS, "risk_appetite": "cautious"})[0].quantile == "p25"


def test_replacement_tiers_and_divergence_on_a_synthetic_pool():
    pool = tuple(PoolPlayer(i, f"p{i}", "A", v * 0.8, v, v * 1.2, q)
                 for i, (v, q) in enumerate([(200, 30), (190, 25), (120, 12), (115, 14), (60, 3), (58, 2), (20, 1), (18, 1)]))
    expected = {p.player_id: max(1, p.quotazione) for p in pool}
    cfg = PricingConfig(tiers_per_class=3, tier_pool=6)
    assert replacement_levels(pool, expected, cfg) == {"A": 20.0}           # the best player expected to cost one credit
    tiers = assign_tiers(pool, cfg)
    assert tiers == {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4}        # three tiers by the two largest gaps, the rest one below
    values = {p.player_id: p.value_p50 for p in pool}
    for a in pool:
        for b in pool:
            if values[a.player_id] > values[b.player_id]:
                assert tiers[a.player_id] <= tiers[b.player_id]           # tiers are monotone
    div = divergence(pool)
    assert div[3] == (pytest.approx(120.0), pytest.approx(-5.0))            # quotazione rank 2 implies 120; he is worth 115
    assert div[2] == (pytest.approx(115.0), pytest.approx(5.0))
    assert div[0] == (pytest.approx(200.0), pytest.approx(0.0))


def test_run_valuation_projects_prices_and_stamps(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    try:
        assert isinstance(result, ValuationRun) and len(result.projections) == 17
        assert result.season_id == 21 and result.giornata == 1 and len(result.rules_hash) == 16
        assert result.settings_snapshot_id == 1 and result.listone_snapshot_id == 1
        assert [s.name for s in result.scenarios] == ["balanced"] and set(result.boards) == {"balanced"}
        assert len(result.run_id) == 25 and result.run_id.startswith("20260830T100000Z-")
        by_id = {p.player_id: p for p in result.projections}
        lautaro = by_id[2764]
        assert lautaro.role_class == "Pc" and lautaro.explain["rate_source"] == "history"
        assert "penalty_rate_season" in lautaro.explain
        assert lautaro.explain["rotation_factor"] == 1.0 and by_id[2640].explain["rotation_factor"] == 0.85
        assert all(result.vor[pid] >= 0 for pid in by_id)                                    # no negative VOR
        assert all(1 <= result.tiers[pid] <= PricingConfig().tiers_per_class + 1 for pid in by_id)
        board = result.boards["balanced"]
        assert set(board.prices) == set(by_id)
        assert all(p.band.p75 <= board.budget for p in board.prices.values())
        assert board.composition["Por"] >= 2 and board.budget <= 500
        assert sum(board.credits_by_class.values()) <= 500                                  # max prices sum sanely
        assert result.implied[2764][0] > 0 and isinstance(result.implied[2764][1], float)
        # every club has a profile, so no "no profile" warning; the template's taker (Calhanoglu) is Inter's
        # alone and a taker is resolved among his own club's players, so the other seven clubs warn. This
        # 17-player fixture is also far short of the league's team-scaled need in most classes (Task 10's
        # fold, unlike the old any-player-at-all check, says so for those too) -- every warning is one of
        # those two kinds, never a third.
        assert not any("no profile" in w for w in result.warnings)
        assert any("penalty taker" in w for w in result.warnings)
        assert all("penalty taker" in w or "supplies the class at" in w for w in result.warnings)
        assert result.summary["team_count"] == 8 and result.summary["market_credits"] == 4000
        assert result.summary["giornate_remaining"] == 37
    finally:
        con.close()


def test_the_run_prices_only_demand_its_own_listone_can_supply(tmp_path, fixture_json, mcp_fixture_json):
    """Dd and Ds each draw half of every module's eleven slots, and no listone
    player ever pins to them: pin_class values every flank player as an E or a
    Dc first, because those outweigh a flank. Priced as modules.yml states it,
    that demand is never satisfied and never bid for, and E and Dc are weighted
    as though they had only their own slots to cover while their players are
    the ones fielding the flanks. So the run prices the demand its own supply
    can carry -- conserved, not dropped."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    try:
        demand, pinned = result.config["demand"], {p.role_class for p in result.projections}
        assert {cls for cls, d in demand.items() if d > 0} <= pinned
        assert demand["Dd"] == demand["Ds"] == 0.0
        assert sum(demand.values()) == pytest.approx(11.0)
        assert demand["E"] > 1.0 and demand["Dc"] > 2.45
        # and it is not bookkeeping: the flank demand now buys a starting slot.
        # Priced off the raw module demand this completion fields one E and two
        # Pc; the E that fills the flanks earns the second place instead.
        board = result.boards["balanced"]
        assert board.composition["E"] == 2 and board.composition["Pc"] == 1
        assert board.credits_by_class["E"] > board.credits_by_class["Dc"]
        # Dd and Ds fold to nothing -- structurally nobody ever pins to them, whatever the
        # listone's size -- and a wholly unsupplied class is never treated as merely "partial"
        # (the warning fires only for 0 < kept < 1), so neither one says anything.
        assert result.config["demand_kept"]["Dd"] == 0.0 and result.config["demand_kept"]["Ds"] == 0.0
        assert not any(w.startswith(("Dd:", "Ds:")) for w in result.warnings)
        # this 17-player fixture is itself far short of the league's team-scaled need in most
        # classes -- need is fixed by modules.yml x team_count, not by how big the listone is --
        # so, unlike the old any-player-at-all check, several other classes do say something here
        assert any("supplies the class at" in w for w in result.warnings)
    finally:
        con.close()


def test_one_listed_player_of_a_class_moves_the_board_by_his_share_of_the_demand(tmp_path, fixture_json, mcp_fixture_json):
    """The fold is continuous in the shortfall: a single listed pure `Dd`
    keeps 1 / (6/11 x 8) of the class's demand, not all of it, and the run
    says so in a warning instead of standing on a knife edge."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    before, con = run(tmp_path)
    con.close()
    con = connect(tmp_path / "data" / "fanta.duckdb")
    con.execute("INSERT INTO players (snapshot_id, player_id, name, team_name, team_short, classic_role, mantra_roles, "
                "mantra_role_codes, quot_current_mantra, age, transfer_flag, raw) "
                "VALUES (1, 99001, 'Terzino D.', 'Inter', 'INT', 'D', ['Dd'], [7], 10, 24, false, '{}'::JSON)")
    con.close()
    after, con = run(tmp_path)
    try:
        kept = 1 / (6 / 11 * 8)
        assert before.config["demand_kept"]["Dd"] == 0.0 and before.config["demand"]["Dd"] == 0.0
        assert after.config["demand_kept"]["Dd"] == pytest.approx(kept)
        # 6/11 x kept is Dd's own remaining share, module-averaged; this fixture is small enough
        # that other classes fold too (a keeper never carries a second role, so a listone this
        # short of goalkeepers folds Por the same "nobody else carries it" way Ds always does),
        # landing part of their own shortfall back in Dd's modules -- so the observed average sits
        # above the bare share but nowhere near the 6/11 a fully-unsupplied class would keep at 0
        assert 6 / 11 * kept < after.config["demand"]["Dd"] < 6 / 11
        assert after.config["demand"]["E"] < before.config["demand"]["E"]
        assert sum(after.config["demand"].values()) == pytest.approx(11.0)
        assert any(w.startswith("Dd: the listone supplies the class at 23%") for w in after.warnings)
        moved = [p.player_id for p in before.pool
                 if after.boards["balanced"].prices[p.player_id].band.p50
                 != before.boards["balanced"].prices[p.player_id].band.p50]
        assert moved, "one listed Dd still moves the board -- by a quarter of a slot, not half a slot per module"
    finally:
        con.close()


def test_the_run_is_deterministic_and_the_hashes_track_their_inputs(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    first, con = run(tmp_path)
    con.close()
    second, con = run(tmp_path)
    con.close()
    assert [p.to_dict() for p in first.projections] == [p.to_dict() for p in second.projections]
    assert first.boards["balanced"].to_dict() == second.boards["balanced"].to_dict()
    assert first.model_hash == second.model_hash and first.inputs_hash == second.inputs_hash

    tuned, con = run(tmp_path, pricing_cfg=PricingConfig(bench_weight=0.2))
    con.close()
    assert tuned.model_hash != first.model_hash and tuned.inputs_hash == first.inputs_hash
    prefs = {**PREFS, "target_composition": {"Por": 2, "W": 2}}
    nudged, con = run(tmp_path, preferences=prefs)
    con.close()
    assert nudged.model_hash != first.model_hash

    note_dir = tmp_path / "kb" / "serie-a" / "teams" / "inter" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "martinez-l.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                            "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: cover\n---\n# note\n")
    noted, con = run(tmp_path)
    con.close()
    assert noted.inputs_hash != first.inputs_hash and noted.model_hash == first.model_hash
    assert {p.player_id: p for p in noted.projections}[2764].explain["rate_source"] == "note"


def test_missing_profiles_and_unresolved_takers_are_warnings_not_refusals(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json, profiles=False)
    profile = write_profile(tmp_path / "kb", "Inter", "INT", europe="none", rotation="0.9")
    # the template's taker, Calhanoglu, is listone id 2194 and resolves; a name the listone cannot have does not
    profile.write_text(profile.read_text(encoding="utf-8").replace("penalties: Calhanoglu", "penalties: Nobody"), encoding="utf-8")
    result, con = run(tmp_path)
    con.close()
    assert any("no profile" in w and "Roma" in w for w in result.warnings)
    assert any("'Nobody'" in w and "Inter" in w for w in result.warnings)
    by_id = {p.player_id: p for p in result.projections}
    assert by_id[5841].explain["rotation_factor"] == 1.0
    assert by_id[2194].explain["penalties_per_presenza"] == 0.0                 # Inter's taker is unresolved: history stands


def test_an_orphan_or_misdeclared_note_warns_instead_of_silently_changing_the_run(tmp_path, fixture_json,
                                                                                  mcp_fixture_json):
    """A note for a player_id the listone lacks is never looked up -- it has
    no effect on a single projection -- but it does enter inputs_hash, so
    without a warning the operator sees a new run_id and believes a note
    that never applied did apply. A team_short that disagrees with the
    listone is the same shape of silent mistake."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    kb = tmp_path / "kb"
    note_dir = kb / "serie-a" / "teams" / "napoli" / "players"
    note_dir.mkdir(parents=True)
    (note_dir / "nobody.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                        "player_id: 999999\nname: Nobody\nteam_short: NAP\ndepth: out\n---\n# n\n")
    (note_dir / "hojlund.md").write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                                         "player_id: 6052\nname: Hojlund\nteam_short: INT\ndepth: starter\n---\n# n\n")
    result, con = run(tmp_path)
    con.close()
    orphan = [w for w in result.warnings if "999999" in w or "Nobody" in w]
    assert len(orphan) == 1 and "not in the listone" in orphan[0] and "no effect" in orphan[0]
    misdeclared = [w for w in result.warnings if "Hojlund" in w]
    assert len(misdeclared) == 1 and "'INT'" in misdeclared[0] and "'NAP'" in misdeclared[0]
    # the note is looked up by player_id regardless of the team_short it declares
    by_id = {p.player_id: p for p in result.projections}
    assert by_id[6052].explain["rate_source"] == "note"


PENALTY_ROWS = [(2764, "Martinez L.", "Inter", "A", 6.5, {"goals": 1, "pen_scored": 1}),
                (2120, "Bastoni", "Inter", "D", 6.5, {"pen_scored": 1}),
                (2194, "Calhanoglu", "Inter", "C", 6.5, {}),
                (6052, "Hojlund", "Napoli", "A", 6.0, {}),
                (5841, "Svilar", "Roma", "P", 6.0, {"goals_conceded": 1})]


def test_a_taker_the_listone_spells_with_an_initial_resolves_and_moves_the_penalties(tmp_path, fixture_json,
                                                                                     mcp_fixture_json):
    """Regression, two of them. The taker was resolved with the matcher built
    for the given-name-first sources, so "Martinez L." -- the listone's own
    spelling, character for character -- never resolved: his club kept
    everyone's historical penalties while the clubs whose taker happened to
    match lost theirs, and the warning told the operator to re-spell a name
    that was already right. And no test drove the non-zero club_penalty_rate
    path at all, which is what takes a non-taker's penalties away."""
    seeded(tmp_path, fixture_json, mcp_fixture_json, rows20=PENALTY_ROWS, penalties="Martinez L.")
    result, con = run(tmp_path)
    con.close()
    assert not any("Inter" in w for w in result.warnings), result.warnings
    by_id = {p.player_id: p for p in result.projections}
    # Inter took 60 penalties over the back season's 30 giornate: the club's rate, not the taker's own history
    assert by_id[2764].explain["penalties_per_presenza"] > 0.0
    assert by_id[2120].explain["penalties_per_presenza"] == 0.0          # a non-taker's history is given to the taker
    assert by_id[2120].explain["penalties_missed_per_presenza"] == 0.0
    assert by_id[5841].explain["penalties_per_presenza"] == 0.0          # Roma's taker resolves too (Calhanoglu is not Roma's)


def test_a_taker_at_a_club_the_voti_history_never_names_warns(tmp_path, fixture_json, mcp_fixture_json):
    """Finding 12, and finding A on top of it. club_penalty_rate is keyed by
    the voti workbook's own club string and looked up by the listone's
    team_name -- two free-text sources, no id, and no alias table on the voti
    side. A promoted club, a rename, or "Hellas Verona" against "Verona" all
    miss. The warning is still owed: the profile's statement about who takes
    the penalties has no effect on the club's own history, and a spelling
    difference is a fixable join.

    Model 3 (open question 11) no longer treats an unmatched club as having no
    rate at all: it prices the taker on the league average instead, the same
    fallback a truly promoted club gets. So the redistribution DOES run here,
    on the league-average rate, not on Inter's own (unreachable) history.

    A club the workbook does name but that simply took no penalties is a real
    0.0 and must stay quiet -- the warning is about the join, not the number."""
    rows = [(pid, name, "Inter Milan" if team == "Inter" else team, role, voto, events)
            for pid, name, team, role, voto, events in PENALTY_ROWS]
    seeded(tmp_path, fixture_json, mcp_fixture_json, rows20=rows, penalties="Martinez L.")
    result, con = run(tmp_path)
    con.close()
    inter = [w for w in result.warnings if w.startswith("Inter:")]
    assert len(inter) == 1 and "league-average rate" in inter[0] and "'Inter'" in inter[0], result.warnings
    assert "Martinez L." in inter[0]
    by_id = {p.player_id: p for p in result.projections}
    # "Inter Milan" (60 penalties over 30 giornate = 2.0/giornata) never matches the
    # listone's "Inter"; the league average over Inter Milan/Napoli/Roma (2.0, 0.0, 0.0)
    # is 2/3 per giornata, and that is what the taker is now priced on
    assert by_id[2764].explain["penalties_per_presenza"] == pytest.approx((2 / 3) * ProjectionConfig().pen_conversion)
    assert by_id[2120].explain["penalties_per_presenza"] == 0.0     # not the taker: redistributed away, same as ever
    # Roma is in the workbook and took no penalty: 0.0 is the honest answer, not a broken join
    assert not any(w.startswith("Roma:") and "penalty rate" in w for w in result.warnings), result.warnings


def test_an_unresolved_taker_says_which_way_it_failed(tmp_path, fixture_json, mcp_fixture_json):
    """"Not found in the listone" for a name the listone has is worse than no
    message: it names the wrong fix. A spelling nothing matches and a spelling
    several players match need different corrections."""
    seeded(tmp_path, fixture_json, mcp_fixture_json, profiles=False)
    write_profile(tmp_path / "kb", "Inter", "INT", europe="none", rotation="1.0", penalties="Martinez")
    result, con = run(tmp_path)
    con.close()
    inter = [w for w in result.warnings if w.startswith("Inter:")]
    assert len(inter) == 1 and "'Martinez'" in inter[0] and "add the initial" in inter[0], inter
    assert "'Martinez L.'" in inter[0]                                    # the candidate it could be, by name


def test_an_unknown_modifier_or_an_empty_d_factor_table_refuses(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["calculate"]["smodf"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    with pytest.raises(ValuationError, match="smodf"):
        run(tmp_path)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload["calculate"]["smodf"] = None
    payload["calculate"]["smodd"] = 1
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()
    with pytest.raises(ValuationError, match="d_factor.yml"):
        run(tmp_path)


def _set_calculate(tmp_path, mutate):
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    mutate(payload["calculate"])
    con.execute("UPDATE league_settings SET payload = ?::JSON WHERE snapshot_id = 1", [json.dumps(payload)])
    con.close()


def test_scoring_note_and_profile_errors_all_become_valuationerror(tmp_path, fixture_json, mcp_fixture_json):
    """Finding 4. The contract lists "voto source unknown" under exit 3; a
    disagreeing bnMls pair, disagreeing assist keys, a malformed player note
    and a malformed club profile are the same shape of "this run cannot be
    made honestly" and must surface the same way -- as ValuationError, which
    commands.rank turns into exit 3 -- not escape as a bare traceback (exit
    1). Only these specific loaders are wrapped: a bare ValueError from
    elsewhere (price_board's, for an ordinary modelling error) must still
    reach the caller unwrapped."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)

    _set_calculate(tmp_path, lambda c: c.__setitem__("sourcev", 9))
    with pytest.raises(ValuationError, match="voto source"):
        run(tmp_path)

    _set_calculate(tmp_path, lambda c: (c.__setitem__("sourcev", 1), c["bnMls"].__setitem__("bmgs", [3, 4])))
    with pytest.raises(ValuationError, match="bnMls"):
        run(tmp_path)

    _set_calculate(tmp_path, lambda c: (c["bnMls"].__setitem__("bmgs", [3, 3]), c["bnMls"].__setitem__("bmasf", [2, 2])))
    with pytest.raises(ValuationError, match="assist"):
        run(tmp_path)

    _set_calculate(tmp_path, lambda c: c["bnMls"].__setitem__("bmasf", [1, 1]))          # restore for what follows

    note_dir = tmp_path / "kb" / "serie-a" / "teams" / "inter" / "players"
    note_dir.mkdir(parents=True)
    bad_note = note_dir / "bad.md"
    bad_note.write_text("---\nupdated: 2026-08-30\nttl: 7d\nconfidence: medium\nsource: x\n"
                        "player_id: 2764\nname: Martinez L.\nteam_short: INT\ndepth: titolare\n---\n# n\n")
    with pytest.raises(ValuationError, match="depth"):
        run(tmp_path)
    bad_note.unlink()

    profile = tmp_path / "kb" / "serie-a" / "teams" / "inter" / "profile.md"
    profile.write_text(profile.read_text(encoding="utf-8").replace("rotation_factor: 1.0", "rotation_factor: 5.0"),
                       encoding="utf-8")
    with pytest.raises(ValuationError, match="rotation_factor"):
        run(tmp_path)


def test_record_run_writes_immutable_rows_and_the_views_follow(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    try:
        record_run(con, result)
        assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM valuations").fetchone()[0] == 17
        assert con.execute("SELECT count(*) FROM valuation_prices").fetchone()[0] == 17
        assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == result.run_id
        assert con.execute("SELECT superseded FROM v_valuation_runs").fetchone()[0] is False
        row = con.execute("SELECT v.role_class, v.tier, v.vor, p.max_p50 FROM v_valuations_current v JOIN v_valuation_prices_current p "
                          "USING (run_id, player_id) WHERE v.player_id = 2764").fetchone()
        assert row[0] == "Pc" and row[1] >= 1 and row[2] >= 0 and row[3] >= 0
        with pytest.raises(duckdb.Error):
            record_run(con, result)                                        # the same run twice is a constraint violation
        again = run_valuation(con, now=NOW, kb_dir=tmp_path / "kb", preferences=PREFS, projection_cfg=ProjectionConfig(),
                              pricing_cfg=PricingConfig(), d_factor=load_d_factor())
        assert again.run_id == result.run_id + "-2"                        # a second run in the same second is kept, not clobbered
        record_run(con, again)
        assert con.execute("SELECT run_id FROM v_valuations_current LIMIT 1").fetchone()[0] == again.run_id
        # the superseded run is still there, whole: a second run appends, it never edits the first
        assert con.execute("SELECT count(*) FROM valuations WHERE run_id = ?", [result.run_id]).fetchone()[0] == 17
        assert con.execute("SELECT count(*) FROM valuation_runs").fetchone()[0] == 2
    finally:
        con.close()


def test_excluded_clubs_refuses_rather_than_quietly_restamping_the_run(tmp_path, fixture_json, mcp_fixture_json):
    """It is hashed into model_hash with the rest of preferences but excludes nobody:
    honouring it silently would spend the reproducibility chain to buy nothing."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    with pytest.raises(PreferencesError, match="excluded_clubs"):
        run(tmp_path, preferences={**PREFS, "excluded_clubs": ["Inter"]})
    assert PREFS["excluded_clubs"] == []            # the shipped default, and it must still run
    result, con = run(tmp_path)
    con.close()
    assert len(result.projections) == 17


def test_a_filtered_run_records_the_scenarios_it_actually_ran(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious"}}}
    full, con = run(tmp_path, preferences=prefs)
    con.close()
    filtered, con = run(tmp_path, preferences=prefs, scenario_names=["value-hunting"])
    con.close()
    assert full.config["scenarios"] == ["balanced", "aggressive-attack", "value-hunting"] == list(full.boards)
    assert filtered.config["scenarios"] == ["value-hunting"] and set(filtered.boards) == {"value-hunting"}
    # the preferences that define all three are still recorded whole; only the model_hash
    # must not move, so a filtered run stays comparable to a full one of the same model
    assert filtered.config["preferences"] == full.config["preferences"]
    assert filtered.model_hash == full.model_hash and filtered.inputs_hash == full.inputs_hash
    # VOR, tiers and divergence are the pool's, not the filter's
    assert filtered.vor == full.vor and filtered.tiers == full.tiers and filtered.implied == full.implied
    # Finding 17: a bad `--scenario` is a usage error, not a malformed file, so
    # it has a class of its own and is deliberately not a PreferencesError --
    # that is what lets the CLI exit 2 here and 3 for a malformed config file.
    with pytest.raises(UnknownScenarioError, match="value-hunting"):
        run(tmp_path, preferences=prefs, scenario_names=["no-such-plan"])
    assert not issubclass(UnknownScenarioError, PreferencesError)


def test_new_run_id_and_model_version():
    assert new_run_id(NOW, "bc74428832035639", "0123456789abcdef") == "20260830T100000Z-0123bc74"
    assert MODEL_VERSION == "3"
    assert MODEL_VERSION and model_hash(ProjectionConfig(), PricingConfig(), PREFS, load_d_factor()) != \
        model_hash(ProjectionConfig(prior_presenze=9), PricingConfig(), PREFS, load_d_factor())


def test_inputs_hash_reads_the_snapshots(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb", read_only=True)
    try:
        profiles, notes = load_profiles(tmp_path / "kb"), load_player_notes(tmp_path / "kb")
        a = inputs_hash(con, profiles=profiles, notes=notes)
        assert len(a) == 16 and a == inputs_hash(con, profiles=profiles, notes=notes)
        assert a != inputs_hash(con, profiles=profiles[1:], notes=notes)
    finally:
        con.close()


def test_inputs_hash_covers_the_team_short_the_profiles_are_joined_on(tmp_path, fixture_json, mcp_fixture_json):
    """Finding 5. build_inputs joins profiles to players on team_short and on
    nothing else, so a typo there (INT -> INR) unjoins a whole club: its
    rotation factor and its penalty taker both stop applying. If team_short is
    not in the payload, two runs that name the same rules_hash, model_hash and
    inputs_hash disagree about real prices -- which is the one thing the stamp
    exists to rule out."""
    seeded(tmp_path, fixture_json, mcp_fixture_json, rows20=PENALTY_ROWS, penalties="Martinez L.")
    kb = tmp_path / "kb"
    first, con = run(tmp_path)
    con.close()
    write_profile(kb, "Inter", "INR", europe="none", rotation="1.0", penalties="Martinez L.")
    second, con = run(tmp_path)
    con.close()
    assert [p.to_dict() for p in second.projections] != [p.to_dict() for p in first.projections]
    assert second.inputs_hash != first.inputs_hash


REBUILT_IDS = ("UPDATE league_settings SET snapshot_id = snapshot_id + 100",
               "UPDATE listone_snapshots SET snapshot_id = snapshot_id + 100",
               "UPDATE players SET snapshot_id = snapshot_id + 100",
               "UPDATE teams SET snapshot_id = snapshot_id + 100",
               "UPDATE advanced_stats SET snapshot_id = snapshot_id + 100",
               ("UPDATE advanced_snapshots SET snapshot_id = snapshot_id + 100, "
                "listone_snapshot_id = listone_snapshot_id + 100"),
               "UPDATE fixtures SET snapshot_id = snapshot_id + 100",
               "UPDATE fixture_snapshots SET snapshot_id = snapshot_id + 100")


def test_inputs_hash_follows_a_rematch_under_the_same_snapshot_id(tmp_path, fixture_json, mcp_fixture_json):
    """Finding 6(a). `ingest advanced --rematch` re-derives a snapshot in
    place: ingest/advanced.py UPDATEs the counts and DELETE/re-INSERTs
    advanced_stats under the *same* snapshot_id, because that row's UNIQUE key
    -- sha256, aliases_sha256, listone_snapshot_id -- is exactly what "the same
    derivation" means. So neither the id nor the raw digests move when the
    match does, and Understat's minutes and xG land on different players while
    the run is stamped identically. Hashing the derivation, not the id, is what
    catches it."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        profiles, notes = load_profiles(tmp_path / "kb"), load_player_notes(tmp_path / "kb")
        before = inputs_hash(con, profiles=profiles, notes=notes)
        moved = con.execute("SELECT snapshot_id, source_id, player_id FROM v_advanced_current "
                            "WHERE player_id IS NOT NULL ORDER BY source_id LIMIT 1").fetchone()
        con.execute("UPDATE advanced_stats SET player_id = player_id + 1 WHERE snapshot_id = ? AND source_id = ?",
                    [moved[0], moved[1]])
        assert inputs_hash(con, profiles=profiles, notes=notes) != before
    finally:
        con.close()


def test_inputs_hash_is_reproducible_from_a_rebuilt_database(tmp_path, fixture_json, mcp_fixture_json):
    """Finding 6(b). data/ is gitignored and documented as rebuildable from
    data/raw/, but every snapshot_id is a DuckDB sequence value minted fresh on
    the rebuild. A hash keyed on those ids names a run nobody can reproduce --
    including the operator who committed it to records/. Keyed on content, the
    same raw files stamp the same run whatever ids they land on."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        profiles, notes = load_profiles(tmp_path / "kb"), load_player_notes(tmp_path / "kb")
        before = inputs_hash(con, profiles=profiles, notes=notes)
        for statement in REBUILT_IDS:
            con.execute(statement)
        assert con.execute("SELECT min(snapshot_id) FROM listone_snapshots").fetchone()[0] > 100
        assert inputs_hash(con, profiles=profiles, notes=notes) == before
    finally:
        con.close()


def test_one_deterministic_tie_break_for_every_per_class_ranking():
    """Finding E. The per-class regroup-and-sort appears six times and carried
    two different tie-breaks: `-value_p50` alone in the exports and the rank
    report, `(-value_p50, player_id)` here. One helper, one order, whichever
    shape the row arrives in -- a Projection, a PoolPlayer, or the export's
    dict row."""
    from fantaclaude.analysis.ordering import by_class, rank_key

    rows = [{"player_id": 3, "role_class": "A", "value_p50": 0.0},
            {"player_id": 1, "role_class": "A", "value_p50": 0.0},
            {"player_id": 2, "role_class": "A", "value_p50": 5.0},
            {"player_id": 9, "role_class": "Pc", "value_p50": 0.0}]
    grouped = by_class(rows)
    assert [r["player_id"] for r in grouped["A"]] == [2, 1, 3]
    assert [r["player_id"] for r in grouped["Pc"]] == [9]
    pool = (PoolPlayer(3, "c", "A", 0.0, 0.0, 0.0, 1), PoolPlayer(1, "a", "A", 0.0, 0.0, 0.0, 1))
    assert [p.player_id for p in by_class(pool)["A"]] == [1, 3]
    assert rank_key(rows[0]) == rank_key(pool[0]) == (-0.0, 3)


def test_a_class_tied_on_value_is_ranked_the_same_way_everywhere(tmp_path, fixture_json, mcp_fixture_json):
    """Finding E, the reason it is not merely duplication. Every player with
    `exp_presenze == 0` sits at `value_p50 == 0.0`, so where the tie-breaks
    disagreed a tier cut landed on a different player than the one
    `rankings.md` printed beside it -- decided by nothing but the order the
    rows happened to arrive in. Here the whole pool is tied and arrives in
    reverse player_id order, which is exactly where the two orders part."""
    import csv as csv_module
    from dataclasses import replace

    from fantaclaude.analysis.exports import write_rankings
    from fantaclaude.analysis.valuation import build_pool

    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path)
    con.close()
    tied = [replace(p, value_p25=0.0, value_p50=0.0, value_p75=0.0) for p in result.projections][::-1]
    pool = build_pool(tied)
    tied_run = replace(result, projections=tied, pool=pool, tiers=assign_tiers(pool, PricingConfig()),
                       implied=divergence(pool))
    _, csv_path = write_rankings(tied_run, tmp_path / "data" / "exports")
    printed = list(csv_module.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    assert printed
    for cls in {r["role_class"] for r in printed}:
        ranked = [r for r in printed if r["role_class"] == cls]
        ids = [int(r["player_id"]) for r in ranked]
        assert ids == sorted(ids), cls
        # and the tier column reads down the table, never back up it
        tiers = [int(r["tier"]) for r in ranked]
        assert tiers == sorted(tiers), (cls, tiers)


def test_exports_render_the_run_and_records_keep_it(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.analysis.exports import export_records, render_exports

    seeded(tmp_path, fixture_json, mcp_fixture_json)
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"target_composition": {"A": 2, "Pc": 2}, "risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious"}}}
    result, con = run(tmp_path, preferences=prefs)
    try:
        record_run(con, result)
        exports = tmp_path / "data" / "exports"
        md, csv, plan = render_exports(result, exports)
        assert md == exports / "rankings.md" and csv == exports / "rankings.csv" and plan == exports / "asta-plan.md"
        text = md.read_text(encoding="utf-8")
        assert result.run_id in text and "Martinez L." in text and "## Pc" in text and "rules " + result.rules_hash in text
        assert "17 players" in text
        lines = csv.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("run_id,player_id,name,team,classic_role,role_class,roles,tier,")
        assert len(lines) == 18 and lines[1].startswith(result.run_id)
        plan_text = plan.read_text(encoding="utf-8")
        for name in ("balanced", "aggressive-attack", "value-hunting"):
            assert f"## {name}" in plan_text
        assert "bid to p75" in plan_text and "bid to p25" in plan_text and "Composition" in plan_text
        assert "We disagree with the market" in plan_text and "Cheap value" in plan_text and "If I lose him" in plan_text

        records = tmp_path / "records"
        written = export_records(con, result.run_id, result.rules_hash, records)
        names = sorted(p.relative_to(records).as_posix() for p in written)
        assert names == [f"league_settings/{result.rules_hash}.parquet", f"valuation_prices/{result.run_id}.parquet",
                         f"valuation_runs/{result.run_id}.parquet", f"valuations/{result.run_id}.parquet"]
        back = con.execute(f"SELECT count(*) FROM read_parquet('{records / 'valuations' / (result.run_id + '.parquet')}')").fetchone()[0]
        assert back == 17
        again = export_records(con, result.run_id, result.rules_hash, records)      # never rewritten
        assert again == []
    finally:
        con.close()


def test_a_board_with_no_legal_completion_warns_instead_of_recording_zeros_in_silence(tmp_path, fixture_json,
                                                                                      mcp_fixture_json):
    """price_board answers NEG when no completion of the roster is legal, and its
    silence is right -- NEG is the honest answer. The caller's was not: every band
    came out 0, the composition empty, `rank` printed nothing, and the run was
    recorded and copied to records/ as parquet, which is never rewritten. It is
    reachable from a rules change alone: a league that raises its goalkeeper
    minimum above pricing.yml's max_goalkeepers."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    payload = json.loads(con.execute("SELECT payload FROM v_league_settings_current").fetchone()[0])
    payload["rosters"] = {**payload.get("rosters", {}), "minrl": [4, 21], "maxrl": [4, 21]}
    con.execute("UPDATE league_settings SET payload = ? WHERE snapshot_id = "
                "(SELECT snapshot_id FROM v_league_settings_current)", [json.dumps(payload)])
    con.close()
    valuation, con = run(tmp_path)
    try:
        balanced = valuation.boards["balanced"]
        assert balanced.completion_value == NEG and all(p.band.p50 == 0 for p in balanced.prices.values())
        named = [w for w in valuation.warnings if "no completion of my roster is legal" in w]
        assert len(named) == 1 and named[0].startswith("balanced:"), valuation.warnings
        assert "4-4 goalkeepers" in named[0] and "caps goalkeepers at 3" in named[0], named[0]
        assert valuation.summary["warnings"] == valuation.warnings          # what `rank` prints is the same list
    finally:
        con.close()
