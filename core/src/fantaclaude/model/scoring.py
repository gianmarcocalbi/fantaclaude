"""Scoring under this league's rules: the fantavoto from the base voto and
the event counts, the voto source, and the modifier flags.

Everything here is read from the `settings/calculate` payload of the
league_settings snapshot in force, never typed. `bnMls` carries each
bonus/malus as a two-element list whose meaning is unverified -- every
pair observed so far is equal (`bmgs [3, 3]`, `bmyc [-0.5, -0.5]`, ...) --
so a pair whose values differ is refused, naming the key: the first league
to set them apart fails loud instead of getting a silently chosen index.
The three assist keys (bmass, bmasf, bmasg) must agree with each other for
the same reason: the voti workbook has one `Ass` column.

The workbook's `Gf` excludes penalty goals (observed 2026-08-29: of 258
rows with a penalty scored, 223 carry Gf = 0), so a penalty goal is scored
through penalty_goal x pen_scored and never double-counted through goal.
`Gs` is non-zero only on goalkeeper rows, so goal_conceded x goals_conceded
needs no role gate. Keys the models do not name (bmcsh, bmycsv, bmcg, bmdg,
bmeg, motm -- all zero in every payload seen) stay raw.

`sourcev` selects the voto source. The workbook's sheets are, in order,
Fantacalcio, Statistico, Italia -- the order the public voti page lists its
three sources -- and `sourcev` is 1 in the observed league, so 1 ->
Fantacalcio is the working hypothesis; `doctor` prints the resolved sheet
so the account holder can check it against the league's own calcolo page.
Any other value is refused.

The modifier fields (stbdf, smod*, skodm) are all null in the observed
league. `smodd` is read as the Mantra D-Factor (the defence modifier -- the
only one the Mantra regolamento offers; "d" for difesa); any *other* key
turning non-null is an unknown modifier, and the projection refuses to run
rather than price a rule it does not model. A falsy value (None, 0, false,
an empty container) reads as off.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

BONUS_KEYS: dict[str, str] = {
    "goal": "bmgs", "penalty_goal": "bmpsc", "assist": "bmass", "goal_conceded": "bmgc",
    "penalty_saved": "bmpsa", "penalty_missed": "bmpns", "yellow": "bmyc", "red": "bmrc",
    "own_goal": "bmog",
}
ASSIST_KEYS = ("bmass", "bmasf", "bmasg")
MODIFIER_KEYS = ("stbdf", "smodg", "smodd", "smodm", "skodm", "smodf", "smodl", "smodp", "smodcp")
D_FACTOR_KEY = "smodd"
VOTO_SOURCES: dict[int, str] = {1: "Fantacalcio", 2: "Statistico", 3: "Italia"}


class ScoringError(ValueError):
    """The settings payload does not carry a scoring table this module can read."""


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pair(calculate: dict[str, Any], key: str) -> float:
    bn = calculate.get("bnMls") or {}
    if key not in bn:
        raise ScoringError(f"bnMls lacks {key}")
    value = bn[key]
    if _number(value):
        return float(value)
    if not isinstance(value, list) or len(value) != 2 or not all(_number(v) for v in value):
        raise ScoringError(f"bnMls.{key} is neither a number nor a pair of numbers: {value!r}")
    if value[0] != value[1]:
        raise ScoringError(f"bnMls.{key} = {value!r}: the two values differ and the pair's meaning is unverified")
    return float(value[0])


@dataclass(frozen=True)
class BonusMalus:
    goal: float
    penalty_goal: float
    assist: float
    goal_conceded: float
    penalty_saved: float
    penalty_missed: float
    yellow: float
    red: float
    own_goal: float

    @classmethod
    def from_calculate(cls, calculate: dict[str, Any]) -> BonusMalus:
        values = {name: _pair(calculate, key) for name, key in BONUS_KEYS.items()}
        present = calculate.get("bnMls") or {}
        assists = {key: _pair(calculate, key) for key in ASSIST_KEYS if key in present}
        if len(set(assists.values())) > 1:
            raise ScoringError(f"the assist keys disagree ({assists}) and the workbook has one Ass column")
        return cls(**values)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class Events:
    goals: float = 0.0
    pen_scored: float = 0.0
    assists: float = 0.0
    goals_conceded: float = 0.0
    pen_saved: float = 0.0
    pen_missed: float = 0.0
    yellow: float = 0.0
    red: float = 0.0
    own_goals: float = 0.0

    def __add__(self, other: Events) -> Events:
        return Events(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)})

    def scaled(self, factor: float) -> Events:
        return Events(**{f.name: getattr(self, f.name) * factor for f in fields(self)})

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def event_points(events: Events, bm: BonusMalus) -> float:
    return (bm.goal * events.goals + bm.penalty_goal * events.pen_scored + bm.assist * events.assists
            + bm.goal_conceded * events.goals_conceded + bm.penalty_saved * events.pen_saved
            + bm.penalty_missed * events.pen_missed + bm.yellow * events.yellow + bm.red * events.red
            + bm.own_goal * events.own_goals)


def fantavoto(voto: float, events: Events, bm: BonusMalus) -> float:
    return voto + event_points(events, bm)


def voto_sheet(calculate: dict[str, Any]) -> str:
    source = calculate.get("sourcev")
    if not _number(source) or source not in VOTO_SOURCES:
        raise ScoringError(f"calculate.sourcev = {source!r} is not a voto source this code knows ({VOTO_SOURCES})")
    return VOTO_SOURCES[int(source)]


@dataclass(frozen=True)
class ModifierStatus:
    d_factor: bool
    d_factor_raw: Any
    unknown_active: tuple[str, ...]

    @property
    def any_active(self) -> bool:
        return self.d_factor or bool(self.unknown_active)

    def to_dict(self) -> dict[str, Any]:
        return {"d_factor": self.d_factor, "d_factor_raw": self.d_factor_raw,
                "unknown_active": list(self.unknown_active)}


def modifier_status(calculate: dict[str, Any]) -> ModifierStatus:
    active = {key: calculate.get(key) for key in MODIFIER_KEYS if calculate.get(key)}
    d_factor = D_FACTOR_KEY in active
    unknown = tuple(key for key in MODIFIER_KEYS if key in active and key != D_FACTOR_KEY)
    return ModifierStatus(d_factor, active.get(D_FACTOR_KEY), unknown)
