import json

import pytest
from fantaclaude.analysis.valuation import UnknownScenarioError, record_run
from fantaclaude.asta.pinned import (
    PinnedRun,
    PinnedRunError,
    load_pinned_run,
    newest_run_id,
)
from fantaclaude.asta.pricing import PricingConfig
from fantaclaude.db.connection import connect
from test_valuation import PREFS, run, seeded


def recorded(tmp_path, fixture_json, mcp_fixture_json, **kw):
    """A seeded workspace with one run recorded; returns (the ValuationRun, an open read-write connection)."""
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    result, con = run(tmp_path, **kw)
    record_run(con, result)
    return result, con


def test_load_pinned_run_reads_the_run_back(tmp_path, fixture_json, mcp_fixture_json):
    prefs = {**PREFS, "scenarios": {"value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json, preferences=prefs)
    try:
        assert newest_run_id(con) == result.run_id
        pinned = load_pinned_run(con)
        assert isinstance(pinned, PinnedRun) and pinned.run_id == result.run_id and not pinned.superseded
        assert pinned.rules_hash == result.rules_hash and pinned.model_hash == result.model_hash
        assert pinned.settings_snapshot_id == 1 and pinned.listone_snapshot_id == 1 and pinned.season_id == 21
        assert len(pinned.players) == 17
        lautaro = pinned.players[2764]
        projection = {p.player_id: p for p in result.projections}[2764]
        assert lautaro.name == "Martinez L." and lautaro.team_short == "INT" and lautaro.roles == ("Pc",)
        assert lautaro.role_class == "Pc" and not lautaro.is_goalkeeper and pinned.players[5841].is_goalkeeper
        assert (lautaro.value_p25, lautaro.value_p50, lautaro.value_p75) == (projection.value_p25, projection.value_p50, projection.value_p75)
        assert lautaro.quotazione == 35 and lautaro.tier == result.tiers[2764]
        # fvm is the listone's own market value, joined from the snapshot the run pinned
        assert lautaro.fvm == 185 and pinned.players[3].fvm == 1
        assert lautaro.pool_player() == result.pool[[p.player_id for p in result.pool].index(2764)]
        assert pinned.pricing_cfg == PricingConfig() and [s.name for s in pinned.scenarios] == ["balanced", "value-hunting"]
        assert pinned.scenario().name == "balanced" and pinned.scenario("value-hunting").max_budget_share_per_role == {"Pc": 0.25}
        with pytest.raises(UnknownScenarioError, match="nope"):
            pinned.scenario("nope")
        assert pinned.demand == result.config["demand_by_module"] and not pinned.demand_rederived
        assert list(pinned.demand) == sorted(pinned.demand)                     # module-code order, as canonical_json stores it
        assert pinned.hard_minimums == {"Por": 1, "Dc": 2}
        assert (pinned.league.budget, pinned.league.team_count, pinned.league.goalkeepers, pinned.league.size) == (500, 8, (2, 6), (23, 40))
        assert pinned.league.source == "league"
        assert pinned.prices["balanced"][2764] == result.boards["balanced"].prices[2764].band
        assert pinned.prices["value-hunting"][2764] == result.boards["value-hunting"].prices[2764].band
        assert pinned.club_names["INT"] == "Inter" and pinned.club_names["ATA"] == "Atalanta"
        names = {c.player_id: c for c in pinned.candidates()}
        assert names[2764].name == "Martinez L." and names[2764].team_name == "Inter" and len(names) == 17
        assert result.run_id in pinned.describe() and "current" in pinned.describe()
        assert lautaro.to_dict()["roles"] == ["Pc"]
    finally:
        con.close()


def test_no_run_a_superseded_run_and_a_run_pinned_by_id(tmp_path, fixture_json, mcp_fixture_json):
    seeded(tmp_path, fixture_json, mcp_fixture_json)
    con = connect(tmp_path / "data" / "fanta.duckdb")
    try:
        with pytest.raises(PinnedRunError, match="no valuation run to pin"):
            load_pinned_run(con)
        with pytest.raises(PinnedRunError, match="no valuation run 'nope'"):
            load_pinned_run(con, "nope")
    finally:
        con.close()
    result, con = run(tmp_path)
    record_run(con, result)
    try:
        # a rules change supersedes the run: nothing to pin without --run, but the run still loads by id and says so
        con.execute("INSERT INTO league_settings (fetched_at, league_id, season_id, matchday, rules_hash, team_count, budget, "
                    "roster_min, roster_max, modules, bench_size, substitutions, payload) SELECT fetched_at, league_id, "
                    "season_id, matchday, 'ffffffffffffffff', team_count, 600, roster_min, roster_max, modules, bench_size, "
                    "substitutions, payload FROM league_settings WHERE snapshot_id = 1")
        assert newest_run_id(con) is None
        with pytest.raises(PinnedRunError, match="superseded"):
            load_pinned_run(con)
        pinned = load_pinned_run(con, result.run_id)
        assert pinned.superseded and "superseded" in pinned.describe()
        assert pinned.league.budget == 500                    # the row the run was priced under, not the newest
    finally:
        con.close()


def test_a_run_recorded_before_demand_by_module_re_derives_it_and_says_so(tmp_path, fixture_json, mcp_fixture_json):
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json)
    try:
        config = json.loads(con.execute("SELECT config FROM valuation_runs WHERE run_id = ?", [result.run_id]).fetchone()[0])
        del config["demand_by_module"]
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(config), result.run_id])
        pinned = load_pinned_run(con)
        assert pinned.demand_rederived and "re-derived" in pinned.describe()
        assert pinned.demand == {code: result.config["demand_by_module"][code] for code in sorted(result.config["demand_by_module"])}
        config["pricing"]["no_such_knob"] = 1
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(config), result.run_id])
        with pytest.raises(PinnedRunError, match="cannot be read back"):
            load_pinned_run(con)
    finally:
        con.close()


def test_the_demand_and_the_hard_minimums_both_come_from_the_run(tmp_path, fixture_json, mcp_fixture_json):
    """modules.yml contributes two things to a price -- the folded demand and
    the hard minimums -- and it is in neither model_hash nor rules_hash, so an
    edit there supersedes no run and changes no model id. Both halves
    therefore come from the run's own config: reading one from the record and
    the other from today's file would price a board that is internally out of
    step, silently."""
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json)
    try:
        stored = json.loads(con.execute("SELECT config FROM valuation_runs WHERE run_id = ?",
                                        [result.run_id]).fetchone()[0])
        assert stored["hard_minimums"] == {"Por": 1, "Dc": 2}
        # a run priced when modules.yml demanded three centre-backs keeps them
        stored["hard_minimums"] = {"Por": 1, "Dc": 3}
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(stored), result.run_id])
        pinned = load_pinned_run(con)
        assert pinned.hard_minimums == {"Por": 1, "Dc": 3} and not pinned.demand_rederived
        # and a run recorded before the key existed re-derives it, and says so
        del stored["hard_minimums"]
        con.execute("UPDATE valuation_runs SET config = ?::JSON WHERE run_id = ?", [json.dumps(stored), result.run_id])
        older = load_pinned_run(con)
        assert older.hard_minimums == {"Por": 1, "Dc": 2} and older.demand_rederived
        assert "re-derived" in older.describe()
    finally:
        con.close()


def test_only_the_scenarios_with_committed_prices_are_pinnable(tmp_path, fixture_json, mcp_fixture_json):
    """`rank --scenario balanced` commits one band, so the night can follow
    one scenario: a `--scenario` naming a scenario preferences.yml defines
    but this run never priced has no committed board behind it, and the
    pinned run neither advertises it nor hands it out."""
    prefs = {**PREFS, "scenarios": {"value-hunting": {"risk_appetite": "cautious", "max_budget_share_per_role": {"Pc": 0.25}}}}
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json, preferences=prefs, scenario_names=["balanced"])
    try:
        assert list(result.boards) == ["balanced"]
        pinned = load_pinned_run(con)
        assert [s.name for s in pinned.scenarios] == ["balanced"] and list(pinned.prices) == ["balanced"]
        assert "value-hunting" not in pinned.describe()
        with pytest.raises(UnknownScenarioError, match="value-hunting"):
            pinned.scenario("value-hunting")
    finally:
        con.close()


def test_a_run_whose_prices_were_never_recorded_cannot_be_pinned(tmp_path, fixture_json, mcp_fixture_json):
    result, con = recorded(tmp_path, fixture_json, mcp_fixture_json)
    try:
        con.execute("DELETE FROM valuation_prices WHERE run_id = ?", [result.run_id])
        with pytest.raises(PinnedRunError, match="no committed prices"):
            load_pinned_run(con)
    finally:
        con.close()
