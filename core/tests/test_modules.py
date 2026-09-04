import itertools
import random

import pytest
from fantaclaude.model.modules import (
    MODULES_YML,
    Fit,
    Module,
    Slot,
    assign,
    assign_weighted,
    load_modules,
)
from fantaclaude.model.roles import Role

R = frozenset


def test_the_eleven_modules_are_exactly_the_league_api_list(mcp_fixture_json):
    modules = load_modules()
    assert set(modules) == set(mcp_fixture_json("lineup_settings")["mods"])
    for module in modules.values():
        assert len(module.slots) == 11
        assert sum(1 for s in module.slots if s.natural == {Role.Por}) == 1


def test_table_header_records_source_and_date():
    text = MODULES_YML.read_text(encoding="utf-8")
    assert "Tabella-sostituzioni-per-schema-2024-2025.pdf" in text
    assert "verified_on: 2026-08-24" in text


def test_slots_transcribed_from_the_official_table():
    m = load_modules()
    labels = lambda code: [s.label for s in m[code].slots]
    assert labels("343") == ["Por", "Dc", "Dc", "Dc/B", "E", "M/C", "C", "E", "W/A", "A/Pc", "W/A"]
    assert labels("4141") == ["Por", "Ds", "Dc", "Dc", "Dd", "M", "C/T", "T", "E/W", "W", "A/Pc"]
    assert labels("4312")[9] == "T/A/Pc"
    assert m["343"].slot_counts() == {"Por": 1, "Dc": 2, "Dc/B": 1, "E": 2, "M/C": 1, "C": 1, "W/A": 2, "A/Pc": 1}


def test_adaptation_matrix_spot_checks():
    m = load_modules()
    e_slot = m["343"].slots[4]                              # the first "E"
    assert e_slot.fit(R({Role.Dd})) is Fit.ADAPTED          # "-1" in the table
    assert e_slot.fit(R({Role.M})) is Fit.FORCED_ONLY       # "-1*"
    assert e_slot.fit(R({Role.W})) is Fit.NO
    t_slot = m["4141"].slots[7]                             # the rule the regolamento singles out:
    assert t_slot.fit(R({Role.W})) is Fit.NO                # in 4-1-4-1 W cannot cover T ...
    assert m["4141"].slots[8].fit(R({Role.T})) is Fit.NO    # ... nor T cover E/W
    dcb = m["352"].slots[3]
    assert dcb.fit(R({Role.B})) is Fit.NATURAL and dcb.fit(R({Role.Dd})) is Fit.FORCED_ONLY


def test_back_three_schemes_use_b_and_back_four_schemes_do_not():
    for code, module in load_modules().items():
        if code.startswith("3"):
            assert module.slots[3].label == "Dc/B"
        else:
            assert not any(Role.B in s.natural for s in module.slots)


def test_a_multi_role_player_takes_the_best_fit_across_his_roles():
    slot = load_modules()["4231"].slots[7]                  # "W/T"
    assert slot.fit(R({Role.E, Role.T})) is Fit.NATURAL     # T natural, even though E alone is only adapted


def test_assign_fields_a_legal_eleven_and_rejects_an_illegal_one():
    m = load_modules()["343"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}),
              R({Role.C}), R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    result = assign(m, roster)
    assert result is not None and sorted(result) == list(range(11))
    roster[7] = R({Role.W})                                  # second E gone: no natural E left
    assert assign(m, roster) is None
    assert assign(m, roster, allow_adapted=True) is None     # W is "no" for E even adapted
    roster[7] = R({Role.Dd})                                 # Dd is adapted for E
    assert assign(m, roster) is None
    assert assign(m, roster, allow_adapted=True) is not None


def test_assign_counts_a_three_role_player_once():
    m = load_modules()["343"]
    flex = R({Role.B, Role.Ds, Role.E})
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), flex, R({Role.M}), R({Role.C}),
              R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A})]
    assert assign(m, roster) is None                         # ten players cannot fill eleven slots
    roster.append(R({Role.E}))
    result = assign(m, roster)
    assert result is not None and len(set(result)) == 11


def test_assign_finds_the_matching_a_greedy_pass_misses():
    """Hand-solved: in 3-4-1-2 the E/T player must go to T so the E-only
    players can take both E slots; a first-come assignment would park him at E."""
    m = load_modules()["3412"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.Dc}), R({Role.E, Role.T}),
              R({Role.E}), R({Role.M}), R({Role.C}), R({Role.Pc}), R({Role.A})]
    assert assign(m, roster) is None                         # two E slots + T from {E/T, E}: one short
    roster.append(R({Role.E}))
    result = assign(m, roster)
    assert result is not None
    t_index = next(i for i, s in enumerate(m.slots) if s.label == "T")
    assert roster[result[t_index]] == R({Role.E, Role.T})


def _brute(module, roster, natural, adapted):
    best = None
    for perm in itertools.permutations(range(len(roster)), len(module.slots)):
        total = 0.0
        for slot, i in zip(module.slots, perm):
            fit = slot.fit(roster[i])
            if fit is Fit.NATURAL:
                total += natural[i]
            elif fit is Fit.ADAPTED:
                total += adapted[i]
            else:
                break
        else:
            if best is None or total > best:
                best = total
    return best


SMALL = Module(code="t", label="test", slots=(
    Slot("Por", R({Role.Por}), R(), R()),
    Slot("Dc", R({Role.Dc}), R({Role.B}), R({Role.Ds})),
    Slot("M/C", R({Role.M, Role.C}), R({Role.T}), R()),
    Slot("A/Pc", R({Role.A, Role.Pc}), R({Role.W}), R({Role.T}))))
POOL = [R({Role.Por}), R({Role.Dc}), R({Role.B}), R({Role.Ds}), R({Role.M}), R({Role.C, Role.T}),
        R({Role.T}), R({Role.W}), R({Role.A}), R({Role.Pc}), R({Role.Dc, Role.M})]


def test_assign_weighted_agrees_with_brute_force_on_small_rosters():
    rng = random.Random(7)
    for _ in range(60):
        roster = rng.sample(POOL, k=rng.randint(4, 7))
        natural = [round(rng.uniform(0, 10), 2) for _ in roster]
        adapted = [max(n - rng.uniform(0.5, 1.5), 0.0) for n in natural]
        oracle = _brute(SMALL, roster, natural, adapted)
        result = assign_weighted(SMALL, roster, natural, adapted)
        if oracle is None:
            assert result is None
        else:
            total, chosen = result
            assert total == pytest.approx(oracle)
            assert len(set(chosen)) == len(SMALL.slots)
            assert all(SMALL.slots[k].fit(roster[i]) in (Fit.NATURAL, Fit.ADAPTED) for k, i in enumerate(chosen))


def test_assign_weighted_prefers_the_natural_fit_when_the_malus_outweighs_the_player():
    m = load_modules()["343"]
    roster = [R({Role.Por}), R({Role.Dc}), R({Role.Dc}), R({Role.B}), R({Role.E}), R({Role.M}),
              R({Role.C}), R({Role.E}), R({Role.W}), R({Role.Pc}), R({Role.A}), R({Role.Dd})]
    natural = [5.0] * 11 + [5.6]                 # the Dd is worth a little more than either E ...
    adapted = [4.0] * 11 + [4.6]                 # ... but not once the out-of-position malus is paid
    total, chosen = assign_weighted(m, roster, natural, adapted)
    assert 11 not in chosen and total == pytest.approx(55.0)
    natural[11], adapted[11] = 7.0, 6.0          # now he is worth fielding adapted at E
    total, chosen = assign_weighted(m, roster, natural, adapted)
    assert 11 in chosen and total == pytest.approx(56.0)


def test_assign_weighted_returns_none_when_no_legal_eleven_exists():
    m = load_modules()["343"]
    roster = [R({Role.Por})] * 3 + [R({Role.Dc})] * 8
    assert assign_weighted(m, roster, [1.0] * 11, [0.0] * 11) is None
    assert assign_weighted(m, roster[:10], [1.0] * 10, [0.0] * 10) is None
