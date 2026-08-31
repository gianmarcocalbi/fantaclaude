"""Opponent pressure: who else can bid on a lot, how deep, and what beating
the room is likely to cost (spec: "an opponent pressure estimate -- who
else needs this slot and how deep they can actually go, from dossiers plus
observed spending"). Displayed beside the band and never folded into it:
the band is what he is worth to me, the pressure is what he will cost.

Per rival, from his ledger: he can bid when the session still lets him buy
in the lot's bucket (goalkeeper or outfield) and his credits exceed one
per other slot he is still *obliged* to fill -- that difference is his
depth. The reservation is against the obligation, not the permission
(`Ledger.required_slots`, the roster floor, never `open_slots`, the
ceiling): under a live session the bounds are exact and the two agree, but
the offline board runs on the league's ranges, where reserving one credit
per slot he merely *may* buy capped every ceiling far too low. From his dossier
(kb/league/participants, loaded at startup, spec "Dossiers are loaded, not
read live"): `avoids` the class is reluctant; `overpays` the class, or the
lot's club among his `favourite_clubs`, is keen; `max_single_share` caps
the depth; an `early` spender with less than half his budget gone is keen
and a `hoarder` in the same spot is reluctant; keen and reluctant together
cancel to neutral. From what he has paid so far: his overpay ratio -- what
he paid over the quotazioni of what he bought, against the room's -- scales
what he is likely to go to. His ceiling is the expected price, times the
intent's factor, times his overpay, never above his depth. The estimate
for the lot is one credit past the keenest rival's ceiling, or the
expected price when nobody can bid. First on the cut-line (spec, "Cut-line,
decided now"): nothing else depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fantaclaude.asta.advisor import Board, Ledger
from fantaclaude.asta.pinned import PinnedPlayer
from fantaclaude.asta.session import SessionSettings
from fantaclaude.kb.participants import Participant

KEEN, NEUTRAL, RELUCTANT = "keen", "neutral", "reluctant"


@dataclass(frozen=True)
class PressureConfig:
    keen_factor: float = 1.25
    reluctant_factor: float = 0.75
    early_spent_share: float = 0.5          # below this share of the budget spent, an early spender is keen and a hoarder reluctant
    min_bid: int = 1


DEFAULT = PressureConfig()


@dataclass(frozen=True)
class Bidder:
    team_id: int
    label: str
    nick: str | None
    intent: str
    credits: int
    depth: int
    overpay: float
    ceiling: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "label": self.label, "nick": self.nick, "intent": self.intent,
                "credits": self.credits, "depth": self.depth, "overpay": round(self.overpay, 3), "ceiling": self.ceiling,
                "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Pressure:
    player_id: int
    expected: int
    bidders: tuple[Bidder, ...]          # ceiling descending
    estimate: int

    def to_dict(self) -> dict[str, Any]:
        return {"player_id": self.player_id, "expected": self.expected, "estimate": self.estimate,
                "bidders": [b.to_dict() for b in self.bidders]}


def _paid_and_quoted(ledger: Ledger, players: dict[int, PinnedPlayer]) -> tuple[int, int]:
    bought = [p for p in ledger.picks if p.player_id in players and players[p.player_id].quotazione > 0]
    return sum(p.cost for p in bought), sum(players[p.player_id].quotazione for p in bought)


def overpay_ratio(ledger: Ledger, players: dict[int, PinnedPlayer]) -> float | None:
    """What the team paid over the quotazioni of what it bought; None before it bought anything priced."""
    paid, quot = _paid_and_quoted(ledger, players)
    return paid / quot if quot else None


def room_ratio(ledgers: dict[int, Ledger], players: dict[int, PinnedPlayer]) -> float:
    """The room's own overpay, every purchase weighted by its quotazione -- one
    broke team's ratio counts for what it bought, not for a whole team's worth."""
    totals = [_paid_and_quoted(ledger, players) for ledger in ledgers.values()]
    paid, quot = sum(p for p, _ in totals), sum(q for _, q in totals)
    return paid / quot if quot else 1.0


def _intent(reasons_keen: list[str], reasons_reluctant: list[str]) -> str:
    if reasons_keen and not reasons_reluctant:
        return KEEN
    if reasons_reluctant and not reasons_keen:
        return RELUCTANT
    return NEUTRAL


def pressure_for(player: PinnedPlayer, expected: int, *, ledgers: dict[int, Ledger], mine: int,
                 settings: SessionSettings, players: dict[int, PinnedPlayer], club_names: dict[str, str],
                 participants: dict[str, Participant], cfg: PressureConfig = DEFAULT,
                 room: float | None = None) -> Pressure:
    # `room` is the room's overpay: invariant across players, so pressure_board
    # passes the one it computed rather than have every lot rescan every
    # ledger's picks. Computed here when the caller prices a single lot.
    if room is None:
        room = room_ratio(ledgers, players)
    club = club_names.get(player.team_short, player.team_short)
    bidders: list[Bidder] = []
    for team_id, ledger in sorted(ledgers.items()):
        if team_id == mine:
            continue
        gk_room, mov_room = ledger.room(settings)
        if (gk_room if player.is_goalkeeper else mov_room) <= 0:
            continue
        depth = ledger.credits - max(0, ledger.required_slots(settings) - 1) * cfg.min_bid
        if depth < cfg.min_bid:
            continue
        keen: list[str] = []
        reluctant: list[str] = []
        depth_note = None
        dossier = participants.get(ledger.nick) if ledger.nick else None
        if dossier is not None:
            if player.role_class in dossier.avoids:
                reluctant.append(f"avoids {player.role_class}")
            if player.role_class in dossier.overpays:
                keen.append(f"overpays {player.role_class}")
            if club in dossier.favourite_clubs:
                keen.append(f"{club} is a favourite club")
            spent_share = ledger.spent / ledger.budget if ledger.budget else 0.0
            if dossier.budget_style == "early" and spent_share < cfg.early_spent_share:
                keen.append("spends early, and has not yet")
            if dossier.budget_style == "hoarder" and spent_share < cfg.early_spent_share:
                reluctant.append("hoards, and still has most of his budget")
            if dossier.max_single_share is not None:
                cap = round(dossier.max_single_share * ledger.budget)
                if cap < depth:
                    depth = cap
                    depth_note = f"never more than {dossier.max_single_share:.0%} of the budget on one player"
        intent = _intent(keen, reluctant)
        team_ratio = overpay_ratio(ledger, players)
        overpay = team_ratio / room if team_ratio is not None and room else 1.0
        factor = {KEEN: cfg.keen_factor, RELUCTANT: cfg.reluctant_factor}.get(intent, 1.0)
        ceiling = int(min(depth, max(cfg.min_bid, round(expected * factor * overpay))))
        reasons = tuple(keen + reluctant + ([depth_note] if depth_note else []))
        bidders.append(Bidder(team_id, ledger.label, ledger.nick, intent, ledger.credits, depth, overpay, ceiling, reasons))
    bidders.sort(key=lambda b: (-b.ceiling, b.team_id))
    estimate = bidders[0].ceiling + cfg.min_bid if bidders else expected
    return Pressure(player.player_id, expected, tuple(bidders), estimate)


def pressure_board(board: Board, participants: dict[str, Participant], cfg: PressureConfig = DEFAULT) -> Board:
    """The board with a pressure estimate beside every unsold player's band."""
    room = room_ratio(board.ledgers, board.players)          # one scan of the picks for the whole board, not one per priced player
    pressure = {pid: pressure_for(board.players[pid], price.expected_price, ledgers=board.ledgers, mine=board.mine,
                                  settings=board.settings, players=board.players, club_names=board.club_names,
                                  participants=participants, cfg=cfg, room=room)
                for pid, price in board.pricing.prices.items()}
    return replace(board, pressure=pressure)
