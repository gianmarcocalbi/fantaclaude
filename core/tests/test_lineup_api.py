import json

import pytest
from conftest import FIXTURE_DIR
from fantaclaude.analysis.weekly.xi import RosterPlayer
from fantaclaude.ingest.lineup_api import (
    CompetitionRangeError,
    CompetitionSelectionError,
    LineupShapeError,
    fetch_lineup,
    load_lineup,
    resolve_giornata,
    resolve_match,
    select_competition,
)
from fantaclaude.ingest.raw import RawStore
from fantaclaude.model.modules import Module, Slot, load_modules
from fantaclaude.model.roles import Role

SAMPLE = json.loads((FIXTURE_DIR / "lineup_sample.json").read_text(encoding="utf-8"))
HOME_TID, AWAY_TID = SAMPLE["home"]["tid"], SAMPLE["away"]["tid"]          # 11560187, 19717181 -- my team is away
AWAY_XI = [4360, 5514, 2296, 6672, 6020, 5559, 5791, 6844, 632, 5687, 7017]        # the fixture's own away.starts ids
AWAY_BENCH = [2097, 6646, 6549, 5844, 6503, 6680, 4502, 6898, 5851, 6821, 5820, 2521]  # the fixture's own away.bench ids
HOME_XI = [5116, 6869, 6956, 5833, 4856, 1933, 6010, 7181, 6398, 6052, 5734]          # the fixture's own home.starts ids

R = frozenset
# Real Mantra roles for the fixture's own player ids, read off the league's
# own listone as it stood for giornata 3 -- not a guess: this is the exact
# data the High review finding's own trace was run against (Caprile Por,
# ..., Da Cunha C/W at starts[5], Frendrup M/C at starts[6], ...). Without
# real roles here every slot fits every player and the positional-mapping
# bug the High finding names is structurally invisible to these tests.
ROLES = {
    4360: R({Role.Por}), 5514: R({Role.Ds, Role.Dc}), 2296: R({Role.Dc}), 6672: R({Role.Dc}),
    6020: R({Role.E, Role.C}), 5559: R({Role.C, Role.W}), 5791: R({Role.M, Role.C}),
    6844: R({Role.T, Role.W}), 632: R({Role.T, Role.A}), 5687: R({Role.W}), 7017: R({Role.Pc}),
    2097: R({Role.Pc}), 6646: R({Role.A}), 6549: R({Role.T}), 5844: R({Role.C, Role.W}),
    6503: R({Role.C, Role.M}), 6680: R({Role.C, Role.M}), 4502: R({Role.Ds, Role.E}),
    6898: R({Role.C, Role.M}), 5851: R({Role.Ds, Role.E}), 6821: R({Role.Dd, Role.E}),
    5820: R({Role.Dc, Role.Dd, Role.Ds}), 2521: R({Role.Por}),
    5116: R({Role.Por}), 6869: R({Role.Dc}), 6956: R({Role.Dc}), 5833: R({Role.Dc}),
    4856: R({Role.E, Role.T}), 1933: R({Role.C}), 6010: R({Role.C, Role.W}), 7181: R({Role.E}),
    6398: R({Role.T, Role.A}), 6052: R({Role.Pc}), 5734: R({Role.A}),
}
# assign(modules["3421"], [ROLES[pid] for pid in AWAY_XI], allow_adapted=True): the true fit, not
# AWAY_XI's own order -- Vasquez/Idzes (Dc/Dc-B) swap, Frendrup/Da Cunha (M/M-C) swap, Zaccagni/Rowe
# (T/T-A) swap; Caprile, Mancini, Ellertsson, Vlasic, Douvikas land where the platform put them anyway.
AWAY_XI_BY_ASSIGN = [4360, 6672, 2296, 5514, 6020, 5791, 5559, 5687, 632, 6844, 7017]
# assign(modules["343"], [ROLES[pid] for pid in HOME_XI], allow_adapted=True): Ramon/Gila (Dc/Dc-B) swap,
# Chukwueze/Wesley (E/E) swap, Isaksen/Soulè (W-A/W-A) swap; the naive positional order (all-legal on its
# own, per the review finding) is still not the permutation `assign` -- and hence this fix -- produces.
HOME_XI_BY_ASSIGN = [5116, 5833, 6956, 6869, 7181, 6010, 1933, 4856, 5734, 6052, 6398]


def _roster(ids):
    return [RosterPlayer(pid, f"p{pid}", ROLES.get(pid, frozenset()), 1, True) for pid in ids]


def test_load_lineup_reads_the_module_the_eleven_and_the_bench_of_my_own_side():
    modules = load_modules()
    roster = _roster(AWAY_XI + AWAY_BENCH)
    submission = load_lineup(SAMPLE, team_id=AWAY_TID, roster=roster, modules=modules, allowed=list(modules))
    assert submission.module in modules and submission.module == "3421"
    assert [x["player_id"] for x in submission.xi] == AWAY_XI_BY_ASSIGN
    assert [b["player_id"] for b in submission.bench] == AWAY_BENCH
    assert submission.lineup_run_id is None
    assert submission.warnings == ()


def test_load_lineup_resolves_the_side_by_team_id_not_position():
    """My team was the AWAY side in the real capture -- a version that
    hardcoded `payload['home']` (a plausible mistake once the plan's
    original per-team signature is corrected to a per-match one) would read
    the wrong module and the wrong eleven here, not merely miss a field."""
    modules = load_modules()
    roster = _roster(HOME_XI)
    submission = load_lineup(SAMPLE, team_id=HOME_TID, roster=roster, modules=modules, allowed=list(modules))
    assert submission.module == "343"                      # home's own module, not away's 3421
    assert [x["player_id"] for x in submission.xi] == HOME_XI_BY_ASSIGN


def test_load_lineup_derives_the_slot_from_the_modules_own_fit_not_positional_order():
    """The High finding: `starts[5]` is Da Cunha (C/W) and `starts[6]` is
    Frendrup (M/C); 3421's own fifth *slot* is `M`, which Da Cunha fits
    neither naturally nor adapted, and its sixth is `M/C`, which he fits
    adapted. A version pairing `starts[k]` with `slots[k]` positionally
    would record Da Cunha at `M` -- illegal, and never what the platform
    actually fielded. There is exactly one `M` slot and one `M/C` slot in
    3421, so this is unambiguous either way the mapping is done."""
    modules = load_modules()
    roster = _roster(AWAY_XI + AWAY_BENCH)
    submission = load_lineup(SAMPLE, team_id=AWAY_TID, roster=roster, modules=modules, allowed=list(modules))
    by_slot = {x["slot"]: x["player_id"] for x in submission.xi}
    assert by_slot["M"] == 5791                   # Frendrup, not Da Cunha
    assert by_slot["M/C"] == 5559                  # Da Cunha, adapted -- not Frendrup
    assert by_slot["Dc/B"] == 5514                 # Vasquez (adapted), not Idzes (starts[3])
    assert by_slot["T"] == 632                     # Zaccagni, natural (T is one of his roles)
    assert by_slot["T/A"] == 6844                  # Rowe, adapted -- not Zaccagni


def test_load_lineup_refuses_an_eleven_no_legal_assignment_can_field():
    """Not a shape problem (right count, right ids) but an outright
    infeasible fit under the module's own table, even with adapted fits --
    `assign` returning `None` must be refused by name, not recorded as a
    confident-looking guess nobody could defend."""
    tiny = {"tt": Module(code="tt", label="test-tiny", slots=(
        Slot("Por", R({Role.Por}), R(), R()),
        Slot("Dc", R({Role.Dc}), R(), R()),
    ))}
    payload = {"home": {"tid": 1, "mdl": "tt", "starts": [{"pid": 100}, {"pid": 101}], "bench": []},
              "away": {"tid": 2, "mdl": "tt", "starts": [], "bench": []}}
    roster = [RosterPlayer(100, "A", R({Role.Por}), 1, True), RosterPlayer(101, "B", R({Role.Por}), 1, True)]
    with pytest.raises(LineupShapeError, match="cannot field"):
        load_lineup(payload, team_id=1, roster=roster, modules=tiny, allowed=["tt"])


def test_load_lineup_refuses_a_team_id_on_neither_side():
    modules = load_modules()
    with pytest.raises(LineupShapeError, match="neither side"):
        load_lineup(SAMPLE, team_id=1, roster=[], modules=modules, allowed=list(modules))


def test_load_lineup_refuses_a_module_this_repo_does_not_know():
    modules = load_modules()
    bad = {**SAMPLE, "away": {**SAMPLE["away"], "mdl": "9999"}}
    with pytest.raises(LineupShapeError, match="9999"):
        load_lineup(bad, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules, allowed=list(modules))


def test_load_lineup_refuses_a_short_eleven():
    """The platform's own `starts` for my side carries fewer entries than
    the module has slots -- a truncated or malformed response, not a
    legality question. The guard must actually fire, not just exist."""
    modules = load_modules()
    truncated = {**SAMPLE, "away": {**SAMPLE["away"], "starts": SAMPLE["away"]["starts"][:5]}}
    with pytest.raises(LineupShapeError, match="5 players"):
        load_lineup(truncated, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules,
                   allowed=list(modules))


def test_load_lineup_refuses_an_entry_missing_pid_with_a_named_error():
    """A `starts`/`bench` entry that loses `pid` (exactly the kind of drift
    this undocumented endpoint's shape guards exist for) must raise the
    adapter's one error type, not an unmapped `KeyError`/`TypeError`."""
    modules = load_modules()
    starts = [dict(e) for e in SAMPLE["away"]["starts"]]
    del starts[0]["pid"]
    bad = {**SAMPLE, "away": {**SAMPLE["away"], "starts": starts}}
    with pytest.raises(LineupShapeError, match="no pid"):
        load_lineup(bad, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules, allowed=list(modules))


def test_load_lineup_refuses_an_entry_with_a_null_pid():
    modules = load_modules()
    bench = [dict(e) for e in SAMPLE["away"]["bench"]]
    bench[0]["pid"] = None
    bad = {**SAMPLE, "away": {**SAMPLE["away"], "bench": bench}}
    with pytest.raises(LineupShapeError, match="no pid"):
        load_lineup(bad, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules, allowed=list(modules))


def test_load_lineup_refuses_a_repeated_player_id_in_the_eleven():
    """Unlike `build_submission`, nothing checked that the eleven were
    distinct -- a malformed response repeating a `pid` must not be recorded
    as a legal-looking XI."""
    modules = load_modules()
    starts = [dict(e) for e in SAMPLE["away"]["starts"]]
    starts[1]["pid"] = starts[0]["pid"]          # a duplicate: same pid recorded twice
    bad = {**SAMPLE, "away": {**SAMPLE["away"], "starts": starts}}
    with pytest.raises(LineupShapeError, match="repeats"):
        load_lineup(bad, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules, allowed=list(modules))


def test_load_lineup_refuses_a_player_named_in_both_xi_and_bench():
    modules = load_modules()
    bench = [dict(e) for e in SAMPLE["away"]["bench"]]
    bench[0]["pid"] = SAMPLE["away"]["starts"][0]["pid"]
    bad = {**SAMPLE, "away": {**SAMPLE["away"], "bench": bench}}
    with pytest.raises(LineupShapeError, match="share"):
        load_lineup(bad, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules, allowed=list(modules))


def test_load_lineup_warns_but_still_records_a_player_who_has_left_the_roster():
    """`roster` is the *current* snapshot; this reads back an already
    finished giornata. A market move since means a name here may no longer
    be on the roster -- `build_submission` refuses that case outright for
    the hand path, but the read-back must not: it records what the
    platform actually did and says so, rather than silently writing `#pid`
    with nothing on stdout to notice it by."""
    modules = load_modules()
    roster = [p for p in _roster(AWAY_XI + AWAY_BENCH) if p.player_id != 5559]      # Da Cunha moved on since
    submission = load_lineup(SAMPLE, team_id=AWAY_TID, roster=roster, modules=modules, allowed=list(modules))
    assert len(submission.xi) == 11
    assert any(str(5559) in w for w in submission.warnings)
    assert [x["name"] for x in submission.xi if x["player_id"] == 5559] == ["#5559"]


def test_load_lineup_ignores_the_allowed_list_and_records_the_module_verbatim():
    """The platform already fielded this module; `load_lineup` records what
    happened rather than second-guessing it against a settings list that
    could have moved since -- a module missing from `allowed` must still be
    recorded, not refused."""
    modules = load_modules()
    submission = load_lineup(SAMPLE, team_id=AWAY_TID, roster=_roster(AWAY_XI + AWAY_BENCH), modules=modules,
                             allowed=["343"])          # away's own module, "3421", is deliberately excluded
    assert submission.module == "3421"


CALENDAR = [
    {"matchDay": 1, "championshipMatchDay": 3, "calculated": False,
     "matches": [{"tIdH": 11560832, "tIdA": 19689008}, {"tIdH": HOME_TID, "tIdA": AWAY_TID}]},
    {"matchDay": 2, "championshipMatchDay": 4, "calculated": False,
     "matches": [{"tIdH": AWAY_TID, "tIdA": 11560636}]},
]


def test_resolve_match_maps_the_championship_matchday_to_the_rounds_own_numbers():
    """The competition's own matchDay (1) and the Serie A championship
    matchday it maps to (3) are different numbers -- a version that
    confused the two would return (3, 3, ...) instead of (1, 3, ...)."""
    assert resolve_match(CALENDAR, championship_matchday=3, team_id=AWAY_TID) == (1, 3, HOME_TID, AWAY_TID)
    assert resolve_match(CALENDAR, championship_matchday=4, team_id=AWAY_TID) == (2, 4, AWAY_TID, 11560636)


def test_resolve_match_refuses_a_championship_matchday_not_in_the_calendar():
    with pytest.raises(LineupShapeError, match="99"):
        resolve_match(CALENDAR, championship_matchday=99, team_id=AWAY_TID)


def test_resolve_match_refuses_a_team_absent_from_that_rounds_matches():
    with pytest.raises(LineupShapeError, match=str(11560636)):
        resolve_match(CALENDAR, championship_matchday=3, team_id=11560636)


COMPETITION = {"id": 539860, "sDay": 3, "eDay": 38, "name": "Fantabalotelli 2026/2027"}
COPPA = {"id": 1, "sDay": 1, "eDay": 38, "name": "Coppa"}


def test_select_competition_takes_the_only_one_without_being_asked():
    assert select_competition([COMPETITION]) == COMPETITION


def test_select_competition_refuses_an_empty_list():
    with pytest.raises(CompetitionSelectionError, match="no competition"):
        select_competition([])
    with pytest.raises(CompetitionSelectionError, match="no competition"):
        select_competition(None)


def test_select_competition_refuses_more_than_one_without_an_explicit_id():
    """[0] must never be taken blindly -- this must refuse, not silently
    pick the first of the two."""
    with pytest.raises(CompetitionSelectionError, match="2 competitions"):
        select_competition([COMPETITION, COPPA])


def test_select_competition_picks_by_id_when_more_than_one_exists():
    assert select_competition([COMPETITION, COPPA], competition_id=1) == COPPA


def test_select_competition_refuses_an_id_absent_from_the_list():
    with pytest.raises(CompetitionSelectionError, match="99999"):
        select_competition([COMPETITION], competition_id=99999)


def test_resolve_giornata_accepts_a_requested_value_inside_the_range():
    assert resolve_giornata(COMPETITION, ahead_giornata=None, requested=10) == 10


def test_resolve_giornata_refuses_a_requested_value_outside_the_range():
    """This competition's own range is 3-38 (`sDay`/`eDay`) -- giornata 2
    was never played under it and giornata 39 never will be."""
    with pytest.raises(CompetitionRangeError, match=r"3-38"):
        resolve_giornata(COMPETITION, ahead_giornata=None, requested=2)
    with pytest.raises(CompetitionRangeError, match=r"3-38"):
        resolve_giornata(COMPETITION, ahead_giornata=None, requested=39)


def test_resolve_giornata_defaults_to_one_behind_the_round_still_ahead():
    assert resolve_giornata(COMPETITION, ahead_giornata=4, requested=None) == 3


def test_resolve_giornata_clamps_the_default_to_the_competitions_own_start():
    """`target_round`'s own answer (the round still ahead) can be this
    competition's very first giornata (`sDay` 3) -- one behind that is
    giornata 2, which this calendario never played at all. A version using
    a hardcoded `<= 1` guard instead of the competition's own `sDay` would
    let this through and fail later with an unrelated resolve_match error."""
    with pytest.raises(CompetitionRangeError, match="starts at 3"):
        resolve_giornata(COMPETITION, ahead_giornata=3, requested=None)


def test_resolve_giornata_refuses_a_default_past_the_competitions_own_end():
    """Symmetric to the sDay case above: `target_round`'s own answer can
    sit past this competition's own last giornata (`eDay` 38) -- e.g. Serie
    A's own calendar still running while this calendario has already
    finished. `ahead_giornata=40` clamps to 39, one past `eDay` -- a version
    checking only `start` would let this through and fail later with an
    unrelated resolve_match error instead of naming the range."""
    with pytest.raises(CompetitionRangeError, match=r"3-38"):
        resolve_giornata(COMPETITION, ahead_giornata=40, requested=None)


def test_resolve_giornata_refuses_with_nothing_to_default_to():
    with pytest.raises(CompetitionRangeError, match="pass --giornata"):
        resolve_giornata(COMPETITION, ahead_giornata=None, requested=None)


class _StubAPI:
    def __init__(self, competitions, calendar, lineup):
        self._competitions, self._calendar, self._lineup = competitions, calendar, lineup
        self.competitions_calls: list[str | None] = []
        self.calendar_calls: list[tuple[int, str | None]] = []
        self.lineup_calls: list[tuple[int, int, int, int, int, str | None]] = []

    async def competitions(self, league=None):
        self.competitions_calls.append(league)
        return self._competitions

    async def competition_calendar(self, idcomp, league=None):
        self.calendar_calls.append((idcomp, league))
        return self._calendar

    async def lineup(self, idcomp, mday, cmday, home_tid, away_tid, league=None):
        self.lineup_calls.append((idcomp, mday, cmday, home_tid, away_tid, league))
        return self._lineup


async def test_fetch_lineup_resolves_the_competition_then_the_five_segments_and_scrubs_emails(tmp_path):
    """The competitions list is read first, the one competition resolves
    `idcomp`, the calendar is read next (never cached), the resolved
    segments feed `api.lineup` in the right order, and the written raw file
    carries no email address even when the payload happens to carry one."""
    leaky = {**SAMPLE, "sign": "reach me at scout@example.it"}
    api = _StubAPI([COMPETITION], CALENDAR, leaky)
    store = RawStore(tmp_path / "raw")
    raw, payload, giornata = await fetch_lineup(api, store, team_id=AWAY_TID, requested_giornata=3,
                                                league="fantabalotelli3")
    assert giornata == 3
    assert api.competitions_calls == ["fantabalotelli3"]
    assert api.calendar_calls == [(539860, "fantabalotelli3")]
    assert api.lineup_calls == [(539860, 1, 3, HOME_TID, AWAY_TID, "fantabalotelli3")]
    assert payload["away"]["tid"] == AWAY_TID
    assert "@" not in raw.path.read_text(encoding="utf-8") and "[email redacted]" in raw.path.read_text(encoding="utf-8")
    assert raw.path.parent.name == "lineup"


async def test_fetch_lineup_defaults_the_giornata_and_never_touches_the_calendar_when_the_range_refuses(tmp_path):
    """A default that clamps below the competition's own start must refuse
    before any calendar/match call is made -- not spend two more requests
    on a championship matchday that never played."""
    api = _StubAPI([COMPETITION], CALENDAR, SAMPLE)
    store = RawStore(tmp_path / "raw")
    with pytest.raises(CompetitionRangeError, match="starts at 3"):
        await fetch_lineup(api, store, team_id=AWAY_TID, requested_giornata=None, ahead_giornata=3)
    assert api.calendar_calls == [] and api.lineup_calls == []
