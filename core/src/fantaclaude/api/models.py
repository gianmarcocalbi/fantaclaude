"""The wire contract of `asta serve`: pydantic mirrors of the payloads the
advisor emits (spec, "Types are generated, not hand-written": these models
are what FastAPI turns into OpenAPI and openapi-typescript turns into the
dashboard's types).

BoardPayload mirrors Board.to_dict() field for field with extra="forbid" on
every model, so drift on either side is a red test (test_api_models), never
a blank dashboard. Nothing here reshapes a payload: the server sends the
advisor's own dict; these models only *describe* it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from fantaclaude.asta.advisor import Board


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BandOut(_Model):
    p25: int
    p50: int
    p75: int


class BidderOut(_Model):
    team_id: int
    label: str
    nick: str | None
    intent: Literal["keen", "neutral", "reluctant"]
    credits: int
    depth: int
    overpay: float
    ceiling: int
    reasons: list[str]


class PressureOut(_Model):
    player_id: int
    expected: int
    estimate: int
    bidders: list[BidderOut]


class SettingsOut(_Model):
    budget: int
    goalkeepers: list[int]          # [low, high]
    outfield: list[int]
    size: list[int]
    game: int
    team_count: int
    source: Literal["session", "league"]


class LedgerOut(_Model):
    team_id: int
    label: str
    nick: str | None
    budget: int
    spent: int
    credits: int
    picks: list[int]
    goalkeepers: int
    outfield: int
    unknown: int
    missing_goalkeepers: int
    missing_outfield: int
    open_slots: int


class LotOut(_Model):
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: list[str]
    tier: int
    band: BandOut | None
    expected_price: int | None
    sold_to: int | None


class LayerOut(_Model):
    count: int
    applied: int
    value_factor: dict[str, float]
    excluded: list[int]
    targets: dict[str, int]
    problems: list[str]
    sha256: str


class PriceRowOut(_Model):
    player_id: int
    name: str
    team_short: str
    role_class: str
    roles: list[str]
    tier: int
    band: BandOut
    expected_price: int
    value_p50: float
    pressure: PressureOut | None = None

    @model_serializer(mode="wrap")
    def _omit_pressure_when_absent(self, handler: SerializerFunctionWrapHandler):
        """Board._row() only adds the "pressure" key when the player has
        pressure (`if p.player_id in self.pressure`); it never emits a null.
        Mirror that here rather than always serialising `pressure: null`.

        Deliberately left without a `-> dict[str, Any]` return annotation:
        pydantic reads that annotation as the model's *serialization-mode*
        JSON schema, so `dict[str, Any]` collapses OpenAPI's PriceRowOut to
        an opaque `{"type": "object"}` and openapi-typescript turns it into
        `[key: string]: unknown`. Leaving it unannotated makes pydantic fall
        back to the model's own field schema (validation-mode, which every
        other model here also uses) -- `pressure` shows up as optional and
        nullable rather than sometimes-absent, which is close enough for a
        generated type and exact for every other field."""
        data = handler(self)
        if self.pressure is None:
            data.pop("pressure", None)
        return data


class BoardPayload(_Model):
    run_id: str
    scenario: str
    settings: SettingsOut
    league_conflicts: list[str]
    problems: list[str]
    status: str | None
    locked: bool | None
    picks: int
    me: LedgerOut
    teams: list[LedgerOut]
    market_credits: int
    inflation: float
    composition: dict[str, int]
    credits_by_class: dict[str, int]
    reserve: int
    budget: int
    slot_price: float
    targets_departed: list[str]
    completion_value: float | None
    selected: int | None
    lot: LotOut | None
    lot_pressure: PressureOut | None
    adjustments: LayerOut
    prices: dict[str, PriceRowOut]


def board_payload(board: Board) -> BoardPayload:
    return BoardPayload.model_validate(board.to_dict())


class TeamOut(_Model):
    team_id: int
    label: str


class MappingOut(_Model):
    mine: int
    nicks: dict[str, str]           # TeamMapping.to_dict stringifies the ids


class HelloPayload(_Model):
    phase: Literal["pending", "live"]
    mode: Literal["feed", "replay", "state"]
    session_code: str | None
    feed: str                       # live | reconnecting | offline | replay | state
    run: str                        # PinnedRun.describe()
    scenario: str | None
    settings: SettingsOut | None
    league_conflicts: list[str]
    note: str | None                # e.g. why the --me/--map flags could not answer the screen
    teams: list[TeamOut]
    participants: list[str]         # dossier nicks, for the mapping screen
    mapping: MappingOut | None
    board: BoardPayload | None


class MappingIn(_Model):
    mine: int
    nicks: dict[int, str] = Field(default_factory=dict)


class AdjustIn(_Model):
    type: Literal["value", "exclude", "target"]
    reason: str
    player: str | None = None
    player_id: int | None = None
    factor: float | None = None
    role_class: str | None = Field(default=None, alias="class")
    count: int | None = None

    def to_entry(self) -> dict[str, Any]:
        """The dict adjustment_from_entry validates — the file's own keys."""
        raw = {"player": self.player, "player_id": self.player_id, "type": self.type,
               "factor": self.factor, "class": self.role_class, "count": self.count, "reason": self.reason}
        return {k: v for k, v in raw.items() if v is not None}


class AdjustResult(_Model):
    described: str
    count: int
    player_id: int | None           # resolved by the server; None for a target
    board: BoardPayload


class RefreshResult(_Model):
    board: BoardPayload
    problems: list[str]
