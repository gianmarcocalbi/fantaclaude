import pytest
from fantaclaude.model.roles import (
    CLASSIC_CODES,
    DEFENSIVE,
    MANTRA_CODES,
    OFFENSIVE,
    ROLE_ORDER,
    ClassicRole,
    Role,
    UnknownRoleCode,
    decode_classic,
    decode_mantra,
    sort_roles,
)


def test_twelve_mantra_roles_and_their_listone_codes():
    assert len(Role) == 12
    assert MANTRA_CODES == {
        6: Role.Por, 7: Role.Dd, 8: Role.Ds, 9: Role.Dc, 10: Role.E, 11: Role.M,
        12: Role.C, 13: Role.W, 14: Role.T, 15: Role.A, 16: Role.Pc, 19: Role.B,
    }
    assert set(MANTRA_CODES.values()) == set(Role)
    assert CLASSIC_CODES == {1: ClassicRole.P, 2: ClassicRole.D, 3: ClassicRole.C, 4: ClassicRole.A}


def test_code_19_is_braccetto():
    assert decode_mantra([19, 8, 10]) == frozenset({Role.B, Role.Ds, Role.E})


def test_defensive_and_offensive_partition_the_outfield_roles():
    assert DEFENSIVE | OFFENSIVE == set(Role) - {Role.Por}
    assert not DEFENSIVE & OFFENSIVE


def test_unknown_code_fails_loud_and_names_the_player():
    with pytest.raises(UnknownRoleCode, match=r"\[20\].*Rossi") as excinfo:
        decode_mantra([9, 20], context="Rossi (id 42)")
    assert excinfo.value.codes == [20]


def test_empty_role_list_is_an_error():
    with pytest.raises(ValueError, match="no Mantra role"):
        decode_mantra([])


def test_classic_decoding():
    assert [decode_classic(c) for c in (1, 2, 3, 4)] == list(ClassicRole)
    with pytest.raises(UnknownRoleCode):
        decode_classic(5)


def test_sort_roles_uses_the_canonical_order():
    assert ROLE_ORDER == tuple(Role)
    assert sort_roles({Role.E, Role.B, Role.Ds}) == [Role.Ds, Role.B, Role.E]
