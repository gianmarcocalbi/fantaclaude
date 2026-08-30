import json
from pathlib import Path

from fantaclaude.asta.advisor import Ledger, TeamMapping, derive
from fantaclaude.asta.pinned import PinnedPlayer
from fantaclaude.asta.pressure import (
    KEEN,
    NEUTRAL,
    RELUCTANT,
    Pressure,
    PressureConfig,
    overpay_ratio,
    pressure_board,
    pressure_for,
    room_ratio,
)
from fantaclaude.asta.session import SessionSettings, session_from_feed
from fantaclaude.asta.state import Pick
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.participants import Participant
from test_advisor import SESSION, node, pinned_run

SETTINGS = session_from_feed({"budget": 500, "game": 2, "roles": {"gk": [2, 2], "mov": [6, 6], "size": [8, 8]}}, team_count=4)
LAUTARO = PinnedPlayer(2764, "Martinez L.", "INT", "A", "Pc", ("Pc",), 200.0, 240.0, 280.0, 35, 1)
SVILAR = PinnedPlayer(5841, "Svilar", "ROM", "P", "Por", ("Por",), 80.0, 100.0, 120.0, 18, 1)
CHEAP = PinnedPlayer(3, "Radunovic", "CAG", "P", "Por", ("Por",), 10.0, 20.0, 30.0, 1, 3)
PLAYERS = {p.player_id: p for p in (LAUTARO, SVILAR, CHEAP)}
CLUBS = {"INT": "Inter", "ROM": "Roma", "CAG": "Cagliari"}


def ledger(team_id, *, nick=None, picks=(), gk=0, mov=0):
    picks = tuple(Pick(pid, team_id, cost, i) for i, (pid, cost) in enumerate(picks))
    return Ledger(team_id, f"t{team_id}", nick, 500, sum(p.cost for p in picks), picks, gk, mov, 0)


def dossier(nick, **kw):
    fields = {"team": None, "budget_style": "steady", "favourite_clubs": (), "overpays": (), "avoids": (), "max_single_share": None}
    fields.update(kw)
    return Participant(path=Path(f"{nick}.md"), nick=nick, front_matter=FrontMatter(None, None, None, None, {}), **fields)


def test_a_rival_bids_only_with_a_slot_and_credits_beyond_one_per_other_slot():
    ledgers = {0: ledger(0), 1: ledger(1, picks=((3, 1),), gk=1), 2: ledger(2, picks=((5841, 18),), gk=2),
               3: ledger(3, picks=((999, 496),), mov=1)}                         # 999: a pick the run cannot name
    assert room_ratio(ledgers, PLAYERS) == 1.0
    p = pressure_for(SVILAR, 20, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS, participants={})
    assert isinstance(p, Pressure) and [b.team_id for b in p.bidders] == [1]           # 2 has both keepers, 3 has 4 credits and 7 slots
    only = p.bidders[0]
    assert only.credits == 499 and only.depth == 499 - 6 and only.intent == NEUTRAL and only.reasons == ()
    assert only.ceiling == 20 and p.estimate == 21 and p.expected == 20
    nobody = pressure_for(SVILAR, 20, ledgers={0: ledger(0), 2: ledgers[2]}, mine=0, settings=SETTINGS, players=PLAYERS,
                          club_names=CLUBS, participants={})
    assert nobody.bidders == () and nobody.estimate == 20


def test_the_dossier_moves_intent_and_caps_depth():
    participants = {"Marco": dossier("Marco", budget_style="early", favourite_clubs=("Inter",), overpays=("Pc",), avoids=("Por",)),
                    "Luca": dossier("Luca", budget_style="hoarder", max_single_share=0.3),
                    "Anna": dossier("Anna", overpays=("Por",), avoids=("Por",)), "Gigi": dossier("Gigi", avoids=("Por",))}
    ledgers = {0: ledger(0), 1: ledger(1, nick="Marco"), 2: ledger(2, nick="Luca"), 3: ledger(3, nick="Anna"),
               4: ledger(4, nick="Nobody"), 5: ledger(5, nick="Gigi")}
    lautaro = pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                           participants=participants)
    by_team = {b.team_id: b for b in lautaro.bidders}
    marco, luca, anna, unknown = by_team[1], by_team[2], by_team[3], by_team[4]
    assert marco.intent == KEEN and marco.ceiling == 125 and set(marco.reasons) == {"overpays Pc", "Inter is a favourite club",
                                                                                     "spends early, and has not yet"}
    assert luca.intent == RELUCTANT and luca.depth == 150 and luca.ceiling == 75                 # 0.3 x 500 caps him; he hoards
    assert "never more than 30% of the budget on one player" in luca.reasons and "hoards" in luca.reasons[0]
    assert anna.intent == NEUTRAL and anna.ceiling == 100 and unknown.intent == NEUTRAL and unknown.reasons == ()
    assert [b.team_id for b in lautaro.bidders] == [1, 3, 4, 5, 2] and lautaro.estimate == 126
    svilar = pressure_for(SVILAR, 20, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                          participants=participants)
    intents = {b.team_id: b.intent for b in svilar.bidders}
    assert intents[5] == RELUCTANT                        # Gigi avoids keepers
    assert intents[1] == NEUTRAL                          # Marco avoids them too, but spends early: the two cancel
    assert intents[3] == NEUTRAL                          # Anna both overpays and avoids them
    assert {b.team_id: b.ceiling for b in svilar.bidders}[5] == 15
    keen_cfg = PressureConfig(keen_factor=2.0)
    assert pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS,
                        participants=participants, cfg=keen_cfg).bidders[0].ceiling == 200


def test_observed_overpaying_scales_the_ceiling_against_the_room():
    ledgers = {0: ledger(0), 1: ledger(1, picks=((5841, 36),), gk=1), 2: ledger(2, picks=((3, 1),), gk=1),
               4: ledger(4, picks=((999, 480),))}                                  # 4: 20 credits, 7 slots -- a thin wallet
    assert overpay_ratio(ledgers[1], PLAYERS) == 2.0 and overpay_ratio(ledgers[2], PLAYERS) == 1.0 and overpay_ratio(ledgers[0], PLAYERS) is None
    room = room_ratio(ledgers, PLAYERS)
    assert room == 37 / 19                                # every purchase weighted by its quotazione, not one ratio per team
    p = pressure_for(LAUTARO, 100, ledgers=ledgers, mine=0, settings=SETTINGS, players=PLAYERS, club_names=CLUBS, participants={})
    by_team = {b.team_id: b for b in p.bidders}
    assert by_team[1].overpay == 2.0 / room and by_team[1].ceiling == round(100 * 2.0 / room)
    assert by_team[2].overpay == 1.0 / room and by_team[2].ceiling == round(100 / room)
    assert by_team[1].ceiling <= by_team[1].depth
    assert json.loads(json.dumps(p.to_dict()))["bidders"][0]["overpay"] == round(2.0 / room, 3)
    # team 4's wallet is too thin to be neutral-priced at 100: the depth clamp binds
    assert by_team[4].depth == 14 and by_team[4].ceiling == 14 and by_team[4].ceiling < by_team[4].depth + 1
    poor = pressure_for(LAUTARO, 100, ledgers={0: ledger(0), 4: ledgers[4]}, mine=0, settings=SETTINGS, players=PLAYERS,
                        club_names=CLUBS, participants={})
    assert poor.bidders[0].ceiling == 14 and poor.estimate == 15         # alone and keenest, the clamp -- not the price -- sets him


def test_pressure_board_puts_an_estimate_beside_every_unsold_band(tmp_path, fixture_json, mcp_fixture_json):
    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    settings = session_from_feed(SESSION, team_count=3)
    participants = {"Marco": dossier("Marco", favourite_clubs=("Inter",), overpays=("Pc",))}
    state = node([(3, 2, 1)], selected=2764)                # Lautaro on the block: lot_pressure is what this proves
    board = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}), participants=participants)
    assert set(board.pressure) == set(board.pricing.prices)
    lautaro = board.pressure[2764]
    assert lautaro.bidders[0].team_id == 0 and lautaro.bidders[0].intent == KEEN and lautaro.estimate == lautaro.bidders[0].ceiling + 1
    assert lautaro.expected == board.pricing.prices[2764].expected_price
    payload = board.to_dict()
    assert payload["prices"]["2764"]["pressure"]["estimate"] == lautaro.estimate
    assert payload["lot_pressure"]["estimate"] == lautaro.estimate and payload["lot_pressure"]["bidders"][0]["intent"] == KEEN
    plain = derive(state, run=pinned, settings=settings, mapping=TeamMapping(mine=1, nicks={0: "Marco"}))
    # not because there is no lot -- state.selected is still 2764 -- but because plain carries no pressure at all
    assert plain.pressure == {} and "pressure" not in plain.to_dict()["prices"]["2764"] and plain.to_dict()["lot_pressure"] is None
    assert pressure_board(plain, participants).to_dict() == payload


LEAGUE = SessionSettings(budget=500, goalkeepers=(2, 6), outfield=(21, 34), size=(23, 40), game=2, team_count=8,
                         source="league")


def test_the_reservation_is_against_the_slots_a_rival_must_fill_not_the_ones_he_may():
    """The offline board -- `asta board --fresh`, the pre-auction planning path
    -- runs on `run.league`, whose bounds are the league's *ranges* (23-40
    here). Reserving one credit per open slot reserved against the roster
    ceiling, so a rival with 20 picks and 30 credits looked 11 credits deep
    instead of the 28 his obligation of 23 actually leaves him, and every
    ceiling on that board was capped far too low. A live session's bounds are
    exact, so nothing there moves."""
    picks = tuple((900 + i, cost) for i, cost in enumerate([23] * 19 + [33]))            # 20 picks, 470 spent
    rival = ledger(1, picks=picks, gk=2, mov=18)
    assert rival.credits == 30 and len(rival.picks) == 20
    assert rival.open_slots(LEAGUE) == 20 and rival.required_slots(LEAGUE) == 3
    # open_slots keeps its meaning -- "slots the session still lets him buy" -- and its place in the payload
    assert rival.to_dict(LEAGUE)["open_slots"] == 20

    p = pressure_for(LAUTARO, 40, ledgers={0: ledger(0), 1: rival}, mine=0, settings=LEAGUE, players=PLAYERS,
                     club_names=CLUBS, participants={})
    only = p.bidders[0]
    assert only.team_id == 1 and only.depth == 28 and only.ceiling == 28 and p.estimate == 29

    # and under a session's exact bounds the obligation and the permission are the same number
    full = ledger(2, picks=tuple((900 + i, 1) for i in range(3)), gk=1, mov=2)
    assert full.required_slots(SETTINGS) == full.open_slots(SETTINGS) == 5


def test_the_rooms_overpay_is_computed_once_for_the_whole_board(tmp_path, fixture_json, mcp_fixture_json, monkeypatch):
    """room_ratio is invariant across players -- it reads every ledger's picks
    and nothing about the lot -- and pressure_board called it once per priced
    player (~550 rescans of the whole room on the real listone)."""
    from fantaclaude.asta import pressure as pressure_module

    _, pinned = pinned_run(tmp_path, fixture_json, mcp_fixture_json)
    board = derive(node([(3, 2, 1)], selected=2764), run=pinned, settings=session_from_feed(SESSION, team_count=3),
                   mapping=TeamMapping(mine=1, nicks={0: "Marco"}))
    real, calls = pressure_module.room_ratio, []

    def counted(ledgers, players):
        calls.append(1)
        return real(ledgers, players)

    monkeypatch.setattr(pressure_module, "room_ratio", counted)
    priced = pressure_board(board, {})
    assert len(priced.pressure) > 1 and len(calls) == 1, (len(priced.pressure), len(calls))
    # and pricing one lot on its own still computes it: the parameter is an optimisation, not a requirement
    pressure_for(LAUTARO, 100, ledgers=board.ledgers, mine=1, settings=board.settings, players=board.players,
                 club_names=board.club_names, participants={})
    assert len(calls) == 2
