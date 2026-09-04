"""Mantra and Classic roles, and the listone's numeric codes for them.

Twelve Mantra roles. The codes are the listone's `marle` values, confirmed in
the MCP spec ("Mantra role codes"); 19 is B, confirmed against a player's
public role badges on 2026-08-24. A code outside this table is an error that
names the player -- never a silent drop, because a striker quietly missing
from the pool is exactly the failure this system exists to avoid.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    Por = "Por"
    Dd = "Dd"
    Ds = "Ds"
    Dc = "Dc"
    B = "B"
    E = "E"
    M = "M"
    C = "C"
    T = "T"
    W = "W"
    A = "A"
    Pc = "Pc"


class ClassicRole(StrEnum):
    P = "P"
    D = "D"
    C = "C"
    A = "A"


MANTRA_CODES: dict[int, Role] = {
    6: Role.Por, 7: Role.Dd, 8: Role.Ds, 9: Role.Dc, 10: Role.E, 11: Role.M,
    # 13 is the trequartista and 14 the ala, not the other way round: confirmed
    # against the downloaded listone (Vlasic 5687 and Da Cunha both carry 13 and
    # are T on fantacalcio.it) and against code 14's population, which is wingers
    # -- Boga, Chukwueze, Conceicao, Cancellieri, Almqvist, Aboukhlal.
    12: Role.C, 13: Role.T, 14: Role.W, 15: Role.A, 16: Role.Pc, 19: Role.B,
}
CLASSIC_CODES: dict[int, ClassicRole] = {
    1: ClassicRole.P, 2: ClassicRole.D, 3: ClassicRole.C, 4: ClassicRole.A,
}

# The regolamento's split: every scheme fields five players from the first
# group and five from the second among its ten outfield players.
DEFENSIVE: frozenset[Role] = frozenset({Role.Dd, Role.Ds, Role.Dc, Role.B, Role.E, Role.M})
OFFENSIVE: frozenset[Role] = frozenset({Role.C, Role.T, Role.W, Role.A, Role.Pc})

ROLE_ORDER: tuple[Role, ...] = tuple(Role)


class UnknownRoleCode(ValueError):
    def __init__(self, codes: Iterable[int], *, context: str = "") -> None:
        self.codes = sorted(set(codes))
        where = f" for {context}" if context else ""
        super().__init__(
            f"unknown role code(s) {self.codes}{where}; known Mantra codes: "
            f"{sorted(MANTRA_CODES)}, Classic codes: {sorted(CLASSIC_CODES)}"
        )


def decode_mantra(codes: Iterable[int], *, context: str = "") -> frozenset[Role]:
    codes = list(codes)
    unknown = [c for c in codes if c not in MANTRA_CODES]
    if unknown:
        raise UnknownRoleCode(unknown, context=context)
    if not codes:
        where = f" for {context}" if context else ""
        raise ValueError(f"no Mantra role{where}: every player carries at least one")
    return frozenset(MANTRA_CODES[c] for c in codes)


def decode_classic(code: int, *, context: str = "") -> ClassicRole:
    try:
        return CLASSIC_CODES[code]
    except KeyError:
        raise UnknownRoleCode([code], context=context) from None


def sort_roles(roles: Iterable[Role]) -> list[Role]:
    return sorted(roles, key=ROLE_ORDER.index)
