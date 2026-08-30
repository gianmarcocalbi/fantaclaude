"""Live adjustments: my beliefs and preferences, applied on top of the pinned
valuation and never inside it (spec, "Live adjustments").

Three kinds with different mechanics. `value` scales a player's projection
by a factor -- p25, p50 and p75 together, so a fitness doubt shrinks the
upside as well as the mean. `exclude` removes him from *my* completion
pool, which raises everyone else at his class through V and lowers nobody.
`target` edits the composition the optimiser starts from: a soft prior it
may depart from, never a bound, and the board reports the departure. Every
entry carries a reason, so the auction record explains itself afterwards.

data/adjustments.yml is a list; the file is mine, hand-editable, and it
outlives the auction. Three surfaces append to it (this module today; an
MCP tool and the dashboard in 2b), so appending is text-first -- the new
entry is rendered and added after the existing text, comments and all --
and the replacement is atomic. A malformed file is an AdjustmentsError the
caller reports while the previous layer stands; a player the pinned run
cannot resolve is a problem the layer names and the entry is inert. Both
are surfaced, never silent (spec, "Name matching"). A later entry for the
same player and kind wins.

    - player: Malen             # the listone's spelling, or player_id: 1234
      type: exclude
      reason: not buying him
    - player: Bastoni
      type: value
      factor: 0.85              # (0, 2]
      reason: limping, reported in the room
    - type: target
      class: Dc                 # a role class
      count: 4                  # the composition to start from
      reason: go heavier on Dc
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fantaclaude.asta.pricing import PoolPlayer
from fantaclaude.atomic import write_atomic
from fantaclaude.ingest.names import AMBIGUOUS, Candidate, Match, match_listone
from fantaclaude.model.demand import ROLE_CLASSES
from fantaclaude.values import is_number

KINDS = ("value", "exclude", "target")
FACTOR_RANGE = (0.0, 2.0)             # exclusive of 0
KEYS = frozenset({"player", "player_id", "type", "factor", "class", "count", "reason"})
HEADER = "# adjustments.yml -- my beliefs and preferences for the auction (fantaclaude asta adjust)\n"


class AdjustmentsError(ValueError):
    """adjustments.yml is malformed; the message names the entry."""


@dataclass(frozen=True)
class Adjustment:
    kind: str
    reason: str
    player: str | None = None
    player_id: int | None = None
    factor: float | None = None
    role_class: str | None = None
    count: int | None = None

    def to_entry(self) -> dict[str, Any]:
        """The file's own shape, keys in reading order."""
        entry: dict[str, Any] = {}
        if self.player is not None:
            entry["player"] = self.player
        if self.player_id is not None:
            entry["player_id"] = self.player_id
        entry["type"] = self.kind
        if self.kind == "value":
            entry["factor"] = self.factor
        if self.kind == "target":
            entry["class"], entry["count"] = self.role_class, self.count
        entry["reason"] = self.reason
        return entry

    def describe(self) -> str:
        who = self.player if self.player is not None else f"player_id {self.player_id}"
        if self.kind == "target":
            return f"target {self.role_class} {self.count} ({self.reason})"
        if self.kind == "value":
            return f"value {who} x{self.factor:g} ({self.reason})"
        return f"exclude {who} ({self.reason})"


def adjustment_from_entry(raw: Any, where: str) -> Adjustment:
    """One entry of the file (or of `asta adjust`'s flags) validated into an Adjustment; the message names `where`."""
    if not isinstance(raw, dict):
        raise AdjustmentsError(f"{where}: must be a mapping, got {raw!r}")
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise AdjustmentsError(f"{where}: unknown key(s) {unknown}; known: {sorted(KEYS)}")
    kind = raw.get("type")
    if kind not in KINDS:
        raise AdjustmentsError(f"{where}: type must be one of {KINDS}, got {kind!r}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AdjustmentsError(f"{where}: reason must say why -- the auction record explains itself afterwards")
    player, player_id = raw.get("player"), raw.get("player_id")
    if kind == "target":
        if player is not None or player_id is not None:
            raise AdjustmentsError(f"{where}: a target names a class, not a player")
        cls, count = raw.get("class"), raw.get("count")
        if cls not in ROLE_CLASSES:
            raise AdjustmentsError(f"{where}: class must be one of {ROLE_CLASSES}, got {cls!r}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise AdjustmentsError(f"{where}: count must be a whole number of players, got {count!r}")
        return Adjustment(kind, reason.strip(), role_class=cls, count=count)
    if (player is None) == (player_id is None):
        raise AdjustmentsError(f"{where}: name the player once -- `player` (the listone's spelling) or `player_id`")
    if player is not None and (not isinstance(player, str) or not player.strip()):
        raise AdjustmentsError(f"{where}: player must be the listone's spelling, got {player!r}")
    if player_id is not None and (isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0):
        raise AdjustmentsError(f"{where}: player_id must be the listone id, got {player_id!r}")
    if raw.get("class") is not None or raw.get("count") is not None:
        raise AdjustmentsError(f"{where}: class and count belong to a target")
    factor = raw.get("factor")
    if kind == "value":
        if not is_number(factor) or not FACTOR_RANGE[0] < float(factor) <= FACTOR_RANGE[1]:
            raise AdjustmentsError(f"{where}: factor must be a number in (0, {FACTOR_RANGE[1]:g}], got {factor!r}")
        factor = float(factor)
    elif factor is not None:
        raise AdjustmentsError(f"{where}: factor belongs to a value adjustment")
    return Adjustment(kind, reason.strip(), player=player.strip() if player else None, player_id=player_id, factor=factor)


def parse_adjustments(text: str, *, where: str = "adjustments.yml") -> list[Adjustment]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdjustmentsError(f"{where}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, list):
        raise AdjustmentsError(f"{where}: the top level must be a list of adjustments")
    return [adjustment_from_entry(raw, f"{where}: entry {i + 1}") for i, raw in enumerate(data)]


def load_adjustments(path: Path) -> list[Adjustment]:
    """The file's entries; no file is no adjustments."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AdjustmentsError(f"{path}: {exc}") from None
    return parse_adjustments(text, where=str(path))


def file_sha256(path: Path) -> str:
    """The layer's stamp for the state file: which adjustments.yml a board was priced under."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def render_entry(adjustment: Adjustment) -> str:
    return yaml.safe_dump([adjustment.to_entry()], sort_keys=False, allow_unicode=True, default_flow_style=False)


def append_adjustment(path: Path, adjustment: Adjustment) -> list[Adjustment]:
    """Reread, append, replace atomically. Text-first, so a hand-written
    comment survives; the whole file is re-parsed before it is written, so
    the file the next refresh reads is known good, and a file that is
    already malformed is not appended to (the hand edit that broke it is a
    person's to fix).

    This is a read-modify-write with no lock: write_atomic guarantees the
    replace itself is torn-free, but not that two concurrent appends don't
    lose one of them -- if a second call reads `existing` before the first
    call's replace lands, the second replace wins and the first entry is
    gone. Today's callers are all single-writer (this module, called
    sequentially), so that race is theoretical for now; the module
    docstring's second writer (an MCP tool) and third (the dashboard) in
    2b are exactly where it stops being theoretical, and that is where a
    lock belongs, not here."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    parse_adjustments(existing, where=str(path))
    text = HEADER if not existing.strip() else existing if existing.endswith("\n") else existing + "\n"
    text += render_entry(adjustment)
    result = parse_adjustments(text, where=str(path))
    write_atomic(path, text.encode("utf-8"))
    return result


@dataclass(frozen=True)
class Resolved:
    adjustment: Adjustment
    player_id: int | None
    note: str | None = None            # why the entry is inert, when it is


@dataclass(frozen=True)
class AdjustmentLayer:
    entries: tuple[Resolved, ...]
    value_factor: dict[int, float]
    excluded: frozenset[int]
    targets: dict[str, int]
    problems: tuple[str, ...]
    sha256: str = ""

    def factor(self, player_id: int) -> float:
        return self.value_factor.get(player_id, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {"count": len(self.entries), "applied": sum(1 for e in self.entries if e.note is None),
                "value_factor": {str(k): v for k, v in sorted(self.value_factor.items())},
                "excluded": sorted(self.excluded), "targets": dict(self.targets), "problems": list(self.problems),
                "sha256": self.sha256}


EMPTY_LAYER = AdjustmentLayer((), {}, frozenset(), {}, ())


def _why(name: str, match: Match, candidates: list[Candidate]) -> str:
    named = {c.player_id: c.name for c in candidates}
    close = ", ".join(repr(named[i]) for i in match.candidates if i in named)
    if match.status == AMBIGUOUS:
        return f"{name!r} is {len(match.candidates)} players of the run ({close}); add the initial the listone uses"
    if match.candidates:
        return f"{name!r} is not how the listone spells {close}; use the listone's spelling"
    return f"{name!r} is not in the pinned run; write him the listone's way -- surname first, then the initial"


def resolve(adjustments: list[Adjustment], candidates: list[Candidate], *, sha256: str = "") -> AdjustmentLayer:
    """Bind every entry to the pinned run's players. An entry that resolves
    to nobody is inert and named in `problems`; nothing is dropped silently."""
    known = {c.player_id for c in candidates}
    entries: list[Resolved] = []
    factors: dict[int, float] = {}
    excluded: set[int] = set()
    targets: dict[str, int] = {}
    problems: list[str] = []
    for a in adjustments:
        if a.kind == "target":
            targets[a.role_class] = a.count
            entries.append(Resolved(a, None))
            continue
        if a.player_id is not None:
            pid = a.player_id if a.player_id in known else None
            note = None if pid is not None else f"player_id {a.player_id} is not in the pinned run"
        else:
            match = match_listone(a.player, candidates)
            pid = match.player_id
            note = None if pid is not None else _why(a.player, match, candidates)
        if pid is None:
            problems.append(f"{a.describe()}: {note}; the adjustment is inert")
        elif a.kind == "value":
            factors[pid] = a.factor
        else:
            excluded.add(pid)
        entries.append(Resolved(a, pid, note))
    return AdjustmentLayer(tuple(entries), factors, frozenset(excluded), targets, tuple(problems), sha256)


def apply_layer(pool: tuple[PoolPlayer, ...], layer: AdjustmentLayer) -> tuple[PoolPlayer, ...]:
    """The pool with every value factor applied to the three quantiles at
    once. Exclusion is not applied here: it is PoolState.excluded, which is
    what makes it reach V rather than annotate a row."""
    if not layer.value_factor:
        return pool
    out = []
    for p in pool:
        f = layer.value_factor.get(p.player_id)
        out.append(p if f is None else PoolPlayer(p.player_id, p.name, p.role_class, p.value_p25 * f, p.value_p50 * f,
                                                  p.value_p75 * f, p.quotazione))
    return tuple(out)
