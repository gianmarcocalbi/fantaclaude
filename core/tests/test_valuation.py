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
from fantaclaude.asta.pricing import PoolPlayer, PricingConfig
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
        assert lautaro.explain["rotation_factor"] == 1.0 and by_id[2640].explain["rotation_factor"] == 0.85
        assert all(result.vor[pid] >= 0 for pid in by_id)                                    # no negative VOR
        assert all(1 <= result.tiers[pid] <= PricingConfig().tiers_per_class + 1 for pid in by_id)
        board = result.boards["balanced"]
        assert set(board.prices) == set(by_id) and all(p.exact for p in board.prices.values())
        assert all(p.band.p75 <= board.budget for p in board.prices.values())
        assert board.composition["Por"] >= 2 and board.budget <= 500
        assert sum(board.credits_by_class.values()) <= 500                                  # max prices sum sanely
        assert result.implied[2764][0] > 0 and isinstance(result.implied[2764][1], float)
        # every club has a profile, so no "no profile" warning; the template's taker (Calhanoglu) is Inter's
        # alone and a taker is resolved among his own club's players, so the other seven clubs warn
        assert not any("no profile" in w for w in result.warnings)
        assert all("penalty taker" in w for w in result.warnings)
        assert result.summary["team_count"] == 8 and result.summary["market_credits"] == 4000
        assert result.summary["giornate_remaining"] == 37
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
    with pytest.raises(PreferencesError, match="value-hunting"):
        run(tmp_path, preferences=prefs, scenario_names=["no-such-plan"])


def test_new_run_id_and_model_version():
    assert new_run_id(NOW, "bc74428832035639", "0123456789abcdef") == "20260830T100000Z-0123bc74"
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


def test_exports_render_the_run_and_records_keep_it(tmp_path, fixture_json, mcp_fixture_json):
    from fantaclaude.analysis.exports import (
        export_records,
        write_asta_plan,
        write_rankings,
    )

    seeded(tmp_path, fixture_json, mcp_fixture_json)
    prefs = {**PREFS, "scenarios": {"aggressive-attack": {"target_composition": {"A": 2, "Pc": 2}, "risk_appetite": "aggressive"},
                                    "value-hunting": {"risk_appetite": "cautious"}}}
    result, con = run(tmp_path, preferences=prefs)
    try:
        record_run(con, result)
        exports = tmp_path / "data" / "exports"
        md, csv = write_rankings(result, exports)
        plan = write_asta_plan(result, exports)
        assert md == exports / "rankings.md" and csv == exports / "rankings.csv" and plan == exports / "asta-plan.md"
        text = md.read_text(encoding="utf-8")
        assert result.run_id in text and "Martinez L." in text and "## Pc" in text and "rules " + result.rules_hash in text
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
