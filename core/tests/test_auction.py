import pytest
from fantaclaude.asta.adjustments import (
    Adjustment,
    AdjustmentsError,
    load_adjustments,
    resolve,
)
from fantaclaude.asta.advisor import TeamMapping, derive
from fantaclaude.asta.auction import Auction, MutationResult, Refresh
from fantaclaude.asta.session import SessionError
from fantaclaude.asta.state import (
    AuctionState,
    LotSelected,
    SaleAdded,
    SettingsChanged,
    StatusChanged,
    apply_snapshot,
    parse_snapshot,
    read_snapshots,
)
from test_advisor import pinned_run
from test_pressure import dossier


def test_every_change_goes_through_mutate_and_reaches_every_listener(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1, nicks={0: "Marco"}))
    assert auction.settings is pinned.league and auction.board.me.credits == 500 and len(auction.board.ledgers) == 8
    seen: list[MutationResult] = []
    auction.subscribe(seen.append)
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    results = [auction.mutate(snap) for snap in snapshots]
    assert [r.events for r in results] == [r.events for r in seen] and len(seen) == 8
    assert results[0].events == (StatusChanged("live", False),) and results[1].events == (SaleAdded(2764, 0, 120),)
    assert results[5].events == (SaleAdded(2120, 0, 45), LotSelected(5841)) and results[6].events == ()
    assert auction.settings.source == "session" and auction.settings.team_count == 3 and auction.settings.goalkeepers == (3, 3)
    assert auction.board.ledgers[0].spent == 165 and auction.board.me.credits == 500
    assert auction.board.league_conflicts == ("teams: 3 in the session, 8 in the league",)
    # the board is a function of the last snapshot: derive() on that snapshot alone is the same board
    state, _ = apply_snapshot(AuctionState.empty(), snapshots[-1])
    direct = derive(state, run=pinned, settings=auction.settings, mapping=auction.mapping)
    assert auction.board.to_dict() == direct.to_dict()
    # a refresh re-derives without a feed event: an exclusion lands, and nothing else moves
    layer = resolve([Adjustment("exclude", "not buying him", player="Hojlund")], pinned.candidates(), sha256="x")
    refreshed = auction.mutate(Refresh(layer=layer))
    assert refreshed.events == () and 6052 not in refreshed.board.pricing.prices and seen[-1] is refreshed
    assert auction.layer is layer and auction.board.layer.sha256 == "x"
    forced = auction.mutate(Refresh())
    assert forced.board.to_dict() == refreshed.board.to_dict()


def test_a_refresh_with_dossiers_populates_pressure_on_the_next_derive(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1, nicks={0: "Marco"}))
    assert auction.participants is None and auction.board.pressure == {}
    participants = {"Marco": dossier("Marco", favourite_clubs=("Inter",), overpays=("Pc",))}
    refreshed = auction.mutate(Refresh(participants=participants))
    assert refreshed.events == () and auction.participants is participants
    assert 2764 in auction.board.pressure and auction.board.pressure != {}


def test_a_malformed_adjustments_file_leaves_the_previous_layer_standing(tmp_path, fixture_json, mcp_fixture_json):
    """A hand edit that breaks adjustments.yml is reported, never fatal: the
    refresh carries no layer, so the layer the board was priced under stands
    (spec, "Adjustments are hot-reloaded")."""
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=0))
    path = tmp_path / "adjustments.yml"
    path.write_text("- player: Hojlund\n  type: exclude\n  reason: knee\n", encoding="utf-8")
    good = resolve(load_adjustments(path), pinned.candidates(), sha256="good")
    auction.mutate(Refresh(layer=good))
    assert 6052 not in auction.board.pricing.prices
    priced = auction.board.to_dict()
    path.write_text("- player: Hojlund\n  type: no-such-kind\n  reason: knee\n", encoding="utf-8")
    with pytest.raises(AdjustmentsError, match="type must be one of"):
        load_adjustments(path)
    result = auction.mutate(Refresh())                     # what the caller does with the error it just reported
    assert result.events == () and auction.layer is good and auction.board.layer.sha256 == "good"
    assert auction.board.to_dict() == priced


def test_a_settings_change_mid_auction_is_an_event_and_re_prices_the_board(tmp_path, fixture_json, mcp_fixture_json, fixture_file):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1))
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    for snap in snapshots[:3]:
        auction.mutate(snap)
    richer = parse_snapshot({**snapshots[2].to_node(), "settings": {**snapshots[2].settings, "budget": 1000}})
    result = auction.mutate(richer)
    assert result.events == (SettingsChanged((("budget", 500, 1000),)),)
    assert auction.settings.budget == 1000 and auction.board.me.credits == 960 and auction.board.ledgers[0].credits == 880
    assert auction.board.league_conflicts[0].startswith("budget: the session plays 1000")
    # a settings node this code cannot read leaves the auction exactly where it was
    before = auction.board.to_dict()
    broken = parse_snapshot({**snapshots[2].to_node(), "settings": {"budget": "lots"}})
    with pytest.raises(SessionError, match="budget"):
        auction.mutate(broken)
    assert auction.board.to_dict() == before and auction.settings.budget == 1000
    with pytest.raises(TypeError):
        auction.mutate("not a change")


def test_a_snapshot_with_no_settings_leaves_the_state_reproducing_its_own_board(tmp_path, fixture_json, mcp_fixture_json,
                                                                                 fixture_file):
    """mutate() kept the settings in force but apply_snapshot replaces
    AuctionState.settings with the snapshot's unconditionally, so a snapshot
    arriving without a settings node announced every key as removed and left
    board.settings and board.state.settings disagreeing. render_state writes
    the *state's* node under `feed`, so a state file written at that moment no
    longer reproduced its own board: read back with no feed, `_settings` saw
    none and fell back to the run's league ranges -- the night's rules swapped
    for the league's, silently, which is the one thing the snapshot module
    exists to prevent."""
    from datetime import UTC, datetime

    from fantaclaude.asta.session import session_from_feed
    from fantaclaude.asta.snapshot import read_state, render_state, write_state
    from fantaclaude.commands.asta import _settings

    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    auction = Auction(pinned, TeamMapping(mine=1, nicks={0: "Marco"}))
    snapshots = read_snapshots(fixture_file("asta_session_sample.jsonl"))
    auction.mutate(snapshots[1])
    assert auction.settings.source == "session" and auction.settings.goalkeepers == (3, 3)

    node = snapshots[2].to_node()
    del node["settings"]                                     # a snapshot the feed sent without one
    silent = auction.mutate(parse_snapshot(node))
    assert not [e for e in silent.events if isinstance(e, SettingsChanged)]      # nothing changed, so nothing is announced
    assert auction.settings.goalkeepers == (3, 3) and auction.board.settings is auction.settings
    assert auction.board.state.settings == auction.settings.raw                 # the board and its own state agree

    path = tmp_path / "data" / "asta-state.json"
    write_state(path, render_state(auction.board, session_code="FA-nri-okm",
                                   written_at=datetime(2026, 9, 5, 22, 30, tzinfo=UTC)))
    stored = read_state(path)
    assert _settings(stored.snapshot, pinned).to_dict() == auction.settings.to_dict()      # the night's rules, not the league's
    reloaded, _ = apply_snapshot(AuctionState.empty(), stored.snapshot)
    again = derive(reloaded, run=pinned, settings=session_from_feed(stored.snapshot.settings,
                                                                   team_count=len(stored.snapshot.teams)),
                   mapping=stored.mapping)
    assert again.to_dict() == auction.board.to_dict()
