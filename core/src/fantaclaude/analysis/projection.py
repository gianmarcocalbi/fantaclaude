"""Projecting a player: expected presenze and fantamedia, as a distribution.

In descending order of how much each part matters (spec, "Projecting a
player"): the fantavoto is recomputed under this league's bonus/malus
(history.py scored every row; the events here are re-applied per presenza
so a taker change or a luck correction goes through the same table); the
fantamedia is shrunk toward the role mean with a weight driven by presenze
(a 7.4 across three appearances is mostly noise); seasons are weighted with
the recent heavier, presenza for presenza; goals and assists are pulled
toward non-penalty xG and xA where Understat covers the season.

Expected presenze = giornate remaining x rate. The rate is the weighted
historical presenze rate, or the note's depth when there is one -- an
absolute statement about now, which last season's minutes cannot make --
times the club's rotation_factor times the note's availability. Rotation
widens the band as much as it lowers the mean: the presenze it removes are
themselves uncertain, so their loss is added to the variance rather than
only subtracted from the mean, which is what prices the uncertainty at the
quantiles.

A defensive-class player's value also gets a D-Factor uplift when a table
is supplied and active: the table's own gradient (slope) at a reference
average of 6.1, applied over a fifth of the excess voto above that
reference, per expected presenza -- and never negative, however the table
is shaped (see `project_player`'s uplift block). Role flexibility has
option value too: roles are a set, and a player who can fill more Mantra
slots is worth more, priced as a fixed bonus per extra role.

The listone quotazione is carried through for the pricing stage and is
read nowhere in this module: a price is not a value, and seeding the value
with the market's price would make the whole apparatus compute nothing.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from fantaclaude.analysis.history import RolePrior, SeasonLine
from fantaclaude.kb.notes import PlayerNote
from fantaclaude.model.d_factor import COUNTED, DFactorTable
from fantaclaude.model.roles import Role, sort_roles
from fantaclaude.model.scoring import BonusMalus, Events, event_points

D_FACTOR_CLASSES: frozenset[str] = frozenset({"Dc", "Dd", "Ds", "E", "M"})


@dataclass(frozen=True)
class ProjectionConfig:
    season_weights: tuple[float, ...] = (1.0, 0.6, 0.35, 0.2)   # this season, then one, two, three back
    prior_presenze: float = 8.0            # the role mean counts as this many presenze
    xg_weight: float = 0.5                 # share of npxG / xA in expected goals / assists
    depth_rates: tuple[tuple[str, float], ...] = (("starter", 0.9), ("contested", 0.65), ("cover", 0.35), ("out", 0.0))
    newcomer_rate: float = 0.5             # presenze rate with no history and no note
    newcomer_dispersion: float = 1.5       # the presenze band of a newcomer, relative to a known player's
    rotation_uncertainty: float = 1.0      # the rotation loss's own sigma, as a share of the loss
    quantile_z: float = 0.6745             # p25 / p75 of a normal
    # roles are a set, not a single slot; a player who can fill more Mantra
    # roles gives the manager more lineup choices, so each role beyond the
    # first is priced as this fraction of extra value (see project_player)
    flex_bonus_per_role: float = 0.03
    pen_conversion: float = 0.8
    d_factor_reference: float = 6.1        # the defensive five's average the uplift is measured against
    fallback_fantamedia: float = 6.0       # with no history for the role at all
    fallback_sd: float = 1.5

    def depth_rate(self, depth: str) -> float:
        return dict(self.depth_rates)[depth]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["season_weights"] = list(self.season_weights)
        d["depth_rates"] = dict(self.depth_rates)
        return d


@dataclass(frozen=True)
class PlayerInputs:
    player_id: int
    name: str
    team_short: str
    team_name: str
    classic_role: str
    roles: frozenset[Role]
    role_class: str
    quotazione: int
    age: int | None
    lines: tuple[SeasonLine, ...]          # newest first
    rotation_factor: float
    note: PlayerNote | None
    penalty_taker: bool
    club_has_taker: bool
    # Penalties (scored + missed) per giornata the club earns, or None when the
    # season the rate is read off never named the club at all -- a promotion, a
    # rename, a different spelling. Absent is not zero: 0.0 is a club that
    # played and won no penalty, and the redistribution below is right to apply
    # it; None is no observation, and there the redistribution does not run.
    club_penalty_rate: float | None


@dataclass(frozen=True)
class Projection:
    player_id: int
    name: str
    team_short: str
    team_name: str
    classic_role: str
    role_class: str
    roles: tuple[str, ...]
    quotazione: int
    exp_presenze: float
    exp_fantamedia: float
    exp_voto: float
    value_p25: float
    value_p50: float
    value_p75: float
    explain: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _per_presenza(line: SeasonLine, cfg: ProjectionConfig, inp: PlayerInputs) -> tuple[Events, dict[str, float]]:
    """The line's events per presenza, luck-corrected and with penalties re-attributed."""
    ev = line.events
    n = line.presenze
    goals, assists = ev.goals, ev.assists
    if line.npxg is not None and line.understat_games:
        goals = (1 - cfg.xg_weight) * ev.goals + cfg.xg_weight * line.npxg
    if line.xa is not None and line.understat_games:
        assists = (1 - cfg.xg_weight) * ev.assists + cfg.xg_weight * line.xa
    pen_scored, pen_missed = ev.pen_scored / n, ev.pen_missed / n
    # The redistribution needs a rate to redistribute. Gated on club_has_taker
    # alone it also fired where there is no observation -- the club promoted
    # into this season, whose rate is read off a season it did not play -- and
    # then gave the taker `0.0 * conversion` penalties while erasing every
    # club-mate's own, so naming a taker was strictly worse than naming none
    # (finding A). No data means do not act, which is exactly the treatment a
    # club with no named taker already gets.
    if inp.club_has_taker and inp.club_penalty_rate is not None:
        rate = inp.club_penalty_rate
        pen_scored = rate * cfg.pen_conversion if inp.penalty_taker else 0.0
        pen_missed = rate * (1 - cfg.pen_conversion) if inp.penalty_taker else 0.0
    events = Events(goals=goals / n, pen_scored=pen_scored, assists=assists / n, goals_conceded=ev.goals_conceded / n,
                    pen_saved=ev.pen_saved / n, pen_missed=pen_missed, yellow=ev.yellow / n, red=ev.red / n,
                    own_goals=ev.own_goals / n)
    return events, {"goals_per_presenza": events.goals, "assists_per_presenza": events.assists,
                    "penalties_per_presenza": events.pen_scored, "penalties_missed_per_presenza": events.pen_missed}


def project_player(inp: PlayerInputs, *, cfg: ProjectionConfig, prior: RolePrior | None, bm: BonusMalus,
                   giornate_remaining: int, current_season: int, d_factor: DFactorTable | None = None) -> Projection:
    n_eff = fm_sum = voto_sum = var_sum = rate_num = rate_den = 0.0
    newest_parts: dict[str, float] | None = None
    for line in inp.lines:                                   # newest first
        offset = current_season - line.season_id
        if offset < 0 or offset >= len(cfg.season_weights) or line.presenze <= 0:
            continue
        w = cfg.season_weights[offset] * line.presenze
        events, parts = _per_presenza(line, cfg, inp)
        fm_line = line.voto_mean + event_points(events, bm)
        n_eff += w
        fm_sum += w * fm_line
        voto_sum += w * line.voto_mean
        var_sum += w * line.fantavoto_var
        rate_num += cfg.season_weights[offset] * line.presenze
        rate_den += cfg.season_weights[offset] * line.giornate
        if newest_parts is None:
            newest_parts = parts
    per_presenza = newest_parts or {"goals_per_presenza": 0.0, "assists_per_presenza": 0.0,
                                    "penalties_per_presenza": 0.0, "penalties_missed_per_presenza": 0.0}

    # Expected fantamedia: shrink toward the target -- the note's prior for a newcomer, else the role mean.
    note = inp.note
    if note is not None and note.prior_fantamedia is not None and n_eff == 0:
        target, target_voto = note.prior_fantamedia, prior.voto_mean if prior else cfg.fallback_fantamedia
    elif prior is not None:
        target, target_voto = prior.fantavoto_mean, prior.voto_mean
    else:
        target, target_voto = cfg.fallback_fantamedia, cfg.fallback_fantamedia
    k = cfg.prior_presenze
    fm_raw = fm_sum / n_eff if n_eff else target
    voto_raw = voto_sum / n_eff if n_eff else target_voto
    shrink = n_eff / (n_eff + k)
    exp_fm = shrink * fm_raw + (1 - shrink) * target
    exp_voto = shrink * voto_raw + (1 - shrink) * target_voto
    sd_match = math.sqrt(var_sum / n_eff) if n_eff else (prior.fantavoto_sd if prior else cfg.fallback_sd)
    if sd_match <= 0:
        sd_match = prior.fantavoto_sd if prior else cfg.fallback_sd
    sigma_fm = sd_match / math.sqrt(n_eff + k)

    # Expected presenze: the note's depth is an absolute statement; else the weighted history; else a newcomer.
    base_rate = rate_num / rate_den if rate_den else None
    if note is not None and note.depth is not None:
        rate0, source = cfg.depth_rate(note.depth), "note"
    elif base_rate is not None:
        rate0, source = base_rate, "history"
    else:
        rate0, source = cfg.newcomer_rate, "newcomer"
    availability = note.availability if note is not None else 1.0
    rate = min(1.0, max(0.0, rate0 * availability * inp.rotation_factor))
    g = giornate_remaining
    exp_presenze = g * rate
    loss = g * rate0 * availability * (1 - inp.rotation_factor)
    dispersion = cfg.newcomer_dispersion if source == "newcomer" else 1.0
    sigma_pres = math.sqrt(g * rate * (1 - rate) * dispersion ** 2 + (loss * cfg.rotation_uncertainty) ** 2)

    # The distribution of the remaining season's fantapunti.
    v50 = exp_presenze * exp_fm
    sigma_v = math.sqrt((exp_fm * sigma_pres) ** 2 + (exp_presenze * sigma_fm) ** 2)
    v25 = max(0.0, v50 - cfg.quantile_z * sigma_v)
    v75 = v50 + cfg.quantile_z * sigma_v

    # D-Factor uplift: the table's own gradient (its slope) at the defensive
    # five's reference average of 6.1, applied over a fifth of this player's
    # excess voto above that reference, per expected presenza. Never negative
    # -- clamped here rather than trusted from the table, because a hand-typed
    # d_factor.yml (Task 10) can carry a lower-points band above a
    # higher-points one, which would otherwise give a negative slope and, with
    # it, a below-zero value_p25.
    uplift = 0.0
    if d_factor is not None and not d_factor.is_empty and inp.role_class in D_FACTOR_CLASSES:
        excess = max(0.0, exp_voto - cfg.d_factor_reference)
        uplift = max(0.0, exp_presenze * d_factor.slope(cfg.d_factor_reference) * excess / COUNTED)
    # Role flexibility has option value: roles are a set, and a player who can
    # fill more Mantra slots gives the manager more lineup choices, so each
    # extra role beyond the first adds a fixed fraction to the value.
    flex = 1 + cfg.flex_bonus_per_role * (len(inp.roles) - 1)
    v25, v50, v75 = ((v25 + uplift) * flex, (v50 + uplift) * flex, (v75 + uplift) * flex)
    if exp_presenze == 0:
        v25 = v50 = v75 = 0.0

    explain = {"n_eff": n_eff, "shrink_weight": shrink, "shrink_target": target, "fantamedia_raw": fm_raw,
               "voto_raw": voto_raw, "sigma_fantamedia": sigma_fm, "sd_match": sd_match,
               "base_rate": base_rate, "rate_source": source, "rate": rate, "depth": note.depth if note else None,
               "availability": availability, "rotation_factor": inp.rotation_factor, "sigma_presenze": sigma_pres,
               "d_factor_uplift": uplift, "flex_bonus": flex, "giornate_remaining": g, **per_presenza}
    return Projection(player_id=inp.player_id, name=inp.name, team_short=inp.team_short, team_name=inp.team_name,
                      classic_role=inp.classic_role, role_class=inp.role_class,
                      roles=tuple(r.value for r in sort_roles(inp.roles)), quotazione=inp.quotazione,
                      exp_presenze=exp_presenze, exp_fantamedia=exp_fm, exp_voto=exp_voto,
                      value_p25=v25, value_p50=v50, value_p75=v75, explain=explain)


def project_all(inputs: Iterable[PlayerInputs], *, cfg: ProjectionConfig, priors: Mapping[str, RolePrior],
                bm: BonusMalus, giornate_remaining: int, current_season: int,
                d_factor: DFactorTable | None = None) -> list[Projection]:
    return [project_player(inp, cfg=cfg, prior=priors.get(inp.classic_role), bm=bm,
                           giornate_remaining=giornate_remaining, current_season=current_season, d_factor=d_factor)
            for inp in inputs]
