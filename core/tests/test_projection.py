from dataclasses import replace
from datetime import date

import pytest
from fantaclaude.analysis.history import RolePrior, SeasonLine
from fantaclaude.analysis.projection import (
    D_FACTOR_CLASSES,
    PlayerInputs,
    Projection,
    ProjectionConfig,
    project_all,
    project_player,
)
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.notes import PlayerNote
from fantaclaude.model.d_factor import Band, DFactorTable
from fantaclaude.model.roles import Role
from fantaclaude.model.scoring import BonusMalus, Events

CFG = ProjectionConfig()
PRIOR_A = RolePrior("A", fantavoto_mean=6.5, fantavoto_sd=1.9, voto_mean=6.0, presenze_rate=0.5, rows=2000)
PRIOR_D = RolePrior("D", fantavoto_mean=6.0, fantavoto_sd=1.1, voto_mean=5.93, presenze_rate=0.5, rows=4000)
TABLE = DFactorTable(bands=(Band(7.0, 6.0), Band(6.5, 3.0), Band(6.0, 1.0), Band(5.5, 0.0)),
                     with_goalkeeper=False, source="synthetic", verified_on=date(2026, 8, 29))


@pytest.fixture
def bm(mcp_fixture_json):
    return BonusMalus.from_calculate(mcp_fixture_json("calculation_settings"))


def line(season_id, presenze, *, giornate=38, voto=6.4, events=None, fv_var=3.0, xg=None, xa=None, npxg=None,
         games=None, team="Inter", role="A"):
    events = events or Events()
    return SeasonLine(season_id=season_id, team=team, classic_role=role, appearances=presenze, presenze=presenze,
                      giornate=giornate, voto_mean=voto, events=events, fantavoto_mean=0.0, fantavoto_var=fv_var,
                      minutes=None, xg=xg, xa=xa, npxg=npxg, understat_games=games)


def inputs(**overrides):
    base = {"player_id": 2764, "name": "Martinez L.", "team_short": "INT", "team_name": "Inter", "classic_role": "A",
            "roles": frozenset({Role.Pc}), "role_class": "Pc", "quotazione": 35, "age": 29,
            "lines": (line(20, 30, events=Events(goals=15, pen_scored=2, assists=6)),),
            "rotation_factor": 1.0, "note": None, "penalty_taker": False, "club_has_taker": False, "club_penalty_rate": 0.0}
    base.update(overrides)
    return PlayerInputs(**base)


def note(**overrides):
    base = {"path": None, "player_id": 2764, "name": "Martinez L.", "team_short": "INT", "depth": None, "availability": 1.0,
            "prior_fantamedia": None, "front_matter": FrontMatter(date(2026, 8, 30), "7d", "medium", "x", {})}
    base.update(overrides)
    return PlayerNote(**base)


def project(inp, **kw):
    """The base fixture's line is season 20; with current_season 20 it is
    'this season' and weighs 1.0, which keeps the arithmetic below exact.
    Tests about recency pass current_season=21 explicitly."""
    kw.setdefault("cfg", CFG)
    kw.setdefault("prior", PRIOR_A)
    kw.setdefault("giornate_remaining", 36)
    kw.setdefault("current_season", 20)
    return project_player(inp, **kw)


def test_a_projection_is_a_distribution_over_remaining_fantapunti(bm):
    p = project(inputs(), bm=bm)
    assert isinstance(p, Projection) and p.player_id == 2764 and p.role_class == "Pc" and p.roles == ("Pc",)
    # 30 presenze in 38 giornate -> rate 0.789 -> 36 x 0.789 = 28.4 expected presenze
    assert p.exp_presenze == pytest.approx(36 * 30 / 38, rel=1e-6)
    # per-presenza events: 0.5 goals, 0.067 penalties, 0.2 assists -> 6.4 + 1.5 + 0.2 + 0.2 = 8.3, shrunk toward 6.5 with k = 8
    raw = 6.4 + 3 * 0.5 + 3 * 2 / 30 + 1 * 0.2
    assert p.explain["fantamedia_raw"] == pytest.approx(raw)
    assert p.exp_fantamedia == pytest.approx((30 * raw + 8 * 6.5) / 38)
    assert p.exp_voto == pytest.approx((30 * 6.4 + 8 * 6.0) / 38)
    assert p.value_p50 == pytest.approx(p.exp_presenze * p.exp_fantamedia)
    assert 0 <= p.value_p25 < p.value_p50 < p.value_p75
    assert p.explain["rate_source"] == "history" and p.explain["n_eff"] == pytest.approx(30.0)
    d = p.to_dict()
    assert d["value_p50"] == pytest.approx(p.value_p50) and d["explain"]["rate_source"] == "history"


def test_quotazione_is_not_in_the_value_path(bm):
    a = project(inputs(quotazione=35), bm=bm)
    b = project(inputs(quotazione=1), bm=bm)
    c = project(inputs(quotazione=99), bm=bm)
    for field in ("exp_presenze", "exp_fantamedia", "exp_voto", "value_p25", "value_p50", "value_p75"):
        assert getattr(a, field) == getattr(b, field) == getattr(c, field), field
    assert a.explain == b.explain == c.explain


def test_rotation_lowers_the_mean_and_widens_the_band(bm):
    still = project(inputs(rotation_factor=1.0), bm=bm)
    rotated = project(inputs(rotation_factor=0.8), bm=bm)
    assert rotated.exp_presenze == pytest.approx(still.exp_presenze * 0.8)
    assert rotated.value_p50 < still.value_p50
    assert rotated.value_p75 - rotated.value_p25 > still.value_p75 - still.value_p25
    # and for a squad player too, where fewer presenze would otherwise narrow a binomial band
    cover_still = project(inputs(lines=(line(20, 12),), rotation_factor=1.0), bm=bm)
    cover_rotated = project(inputs(lines=(line(20, 12),), rotation_factor=0.8), bm=bm)
    assert cover_rotated.value_p75 - cover_rotated.value_p25 > cover_still.value_p75 - cover_still.value_p25


def test_shrinkage_is_driven_by_presenze(bm):
    hot_streak = project(inputs(lines=(line(20, 3, voto=7.4),)), bm=bm)
    full_season = project(inputs(lines=(line(20, 33, voto=7.4),)), bm=bm)
    assert PRIOR_A.fantavoto_mean < hot_streak.exp_fantamedia < full_season.exp_fantamedia < 7.4
    assert hot_streak.explain["shrink_weight"] == pytest.approx(3 / 11)
    assert full_season.explain["shrink_weight"] == pytest.approx(33 / 41)
    assert hot_streak.explain["sigma_fantamedia"] > full_season.explain["sigma_fantamedia"]


def test_recent_seasons_weigh_more(bm):
    older_good = project(inputs(lines=(line(20, 30, voto=6.0), line(19, 30, voto=7.0))), bm=bm, current_season=21)
    recent_good = project(inputs(lines=(line(20, 30, voto=7.0), line(19, 30, voto=6.0))), bm=bm, current_season=21)
    assert recent_good.exp_fantamedia > older_good.exp_fantamedia
    assert recent_good.explain["n_eff"] == pytest.approx(30 * 0.6 + 30 * 0.35)          # offsets 1 and 2 from season 21
    # the current season counts fully, presenza for presenza
    with_current = project(inputs(lines=(line(21, 2, giornate=2, voto=8.0), line(20, 30, voto=6.0))), bm=bm,
                           current_season=21)
    assert with_current.explain["n_eff"] == pytest.approx(2 * 1.0 + 30 * 0.6)
    without_current = project(inputs(lines=(line(20, 30, voto=6.0),)), bm=bm, current_season=21)
    assert with_current.exp_fantamedia > without_current.exp_fantamedia
    # a season older than the weights reach is ignored
    ancient = project(inputs(lines=(line(20, 30, voto=6.0), line(15, 30, voto=9.0))), bm=bm, current_season=21)
    assert ancient.explain["n_eff"] == pytest.approx(30 * 0.6)


def test_luck_correction_moves_goals_toward_npxg_and_assists_toward_xa(bm):
    lucky = inputs(lines=(line(20, 30, events=Events(goals=15), xg=9.0, npxg=9.0, xa=2.0, games=30),))
    plain = inputs(lines=(line(20, 30, events=Events(goals=15)),))
    corrected = project(lucky, bm=bm)
    uncorrected = project(plain, bm=bm)
    assert corrected.exp_fantamedia < uncorrected.exp_fantamedia
    assert corrected.explain["goals_per_presenza"] == pytest.approx((0.5 * 15 + 0.5 * 9.0) / 30)
    assert uncorrected.explain["goals_per_presenza"] == pytest.approx(0.5)
    unlucky = project(inputs(lines=(line(20, 30, events=Events(goals=5, assists=1), npxg=9.0, xg=9.0, xa=4.0, games=30),)), bm=bm)
    assert unlucky.explain["goals_per_presenza"] == pytest.approx(7.0 / 30)
    assert unlucky.explain["assists_per_presenza"] == pytest.approx(2.5 / 30)


def test_a_note_depth_replaces_the_base_rate_and_availability_multiplies(bm):
    cover = project(inputs(note=note(depth="cover")), bm=bm)
    assert cover.explain["rate_source"] == "note" and cover.exp_presenze == pytest.approx(36 * 0.35)
    injured = project(inputs(note=note(availability=0.5)), bm=bm)
    assert injured.exp_presenze == pytest.approx(36 * 30 / 38 * 0.5)
    out = project(inputs(note=note(depth="out")), bm=bm)
    assert out.exp_presenze == 0.0 and out.value_p50 == 0.0 and out.value_p75 == 0.0
    assert CFG.depth_rate("starter") == 0.9 and CFG.depth_rate("contested") == 0.65


def test_a_newcomer_projects_from_the_note_prior_or_the_role_mean_with_a_wide_band(bm):
    unknown = project(inputs(lines=()), bm=bm)
    assert unknown.explain["rate_source"] == "newcomer" and unknown.exp_presenze == pytest.approx(36 * 0.5)
    assert unknown.exp_fantamedia == pytest.approx(PRIOR_A.fantavoto_mean) and unknown.explain["n_eff"] == 0
    known_starter = project(inputs(lines=(line(20, 30),)), bm=bm)
    assert (unknown.value_p75 - unknown.value_p25) / unknown.value_p50 > (known_starter.value_p75 - known_starter.value_p25) / known_starter.value_p50
    with_prior = project(inputs(lines=(), note=note(depth="starter", prior_fantamedia=7.2)), bm=bm)
    assert with_prior.exp_fantamedia == pytest.approx(7.2) and with_prior.exp_presenze == pytest.approx(36 * 0.9)
    assert with_prior.explain["shrink_target"] == 7.2
    no_prior_at_all = project(inputs(lines=()), bm=bm, prior=None)
    assert no_prior_at_all.exp_fantamedia == pytest.approx(CFG.fallback_fantamedia)


def test_penalties_follow_the_named_taker(bm):
    history = (line(20, 30, events=Events(goals=10, pen_scored=5)),)
    no_taker_named = project(inputs(lines=history), bm=bm)
    taker = project(inputs(lines=history, penalty_taker=True, club_has_taker=True, club_penalty_rate=0.2), bm=bm)
    demoted = project(inputs(lines=history, penalty_taker=False, club_has_taker=True, club_penalty_rate=0.2), bm=bm)
    assert demoted.explain["penalties_per_presenza"] == 0.0 and demoted.exp_fantamedia < no_taker_named.exp_fantamedia
    assert taker.explain["penalties_per_presenza"] == pytest.approx(0.2 * CFG.pen_conversion)
    assert taker.explain["penalties_missed_per_presenza"] == pytest.approx(0.2 * (1 - CFG.pen_conversion))
    assert taker.exp_fantamedia > demoted.exp_fantamedia
    # with nobody named, history stands: 5 penalties over 30 presenze
    assert no_taker_named.explain["penalties_per_presenza"] == pytest.approx(5 / 30)


def test_the_d_factor_uplift_applies_only_when_active_and_only_to_defensive_classes(bm):
    assert D_FACTOR_CLASSES == frozenset({"Dc", "Dd", "Ds", "E", "M"})
    dc = inputs(player_id=2120, classic_role="D", roles=frozenset({Role.Dc}), role_class="Dc",
                lines=(line(20, 34, voto=6.6, role="D", events=Events()),))
    off = project(dc, bm=bm, prior=PRIOR_D)
    on = project(dc, bm=bm, prior=PRIOR_D, d_factor=TABLE)
    assert off.explain["d_factor_uplift"] == 0.0 and on.explain["d_factor_uplift"] > 0
    # slope 4 points per voto unit around the 6.1 reference, a fifth of the excess voto, per presenza
    excess = on.exp_voto - CFG.d_factor_reference
    assert on.explain["d_factor_uplift"] == pytest.approx(on.exp_presenze * 4.0 * excess / 5)
    assert on.value_p50 == pytest.approx(off.value_p50 + on.explain["d_factor_uplift"])
    assert on.value_p25 - off.value_p25 == pytest.approx(on.explain["d_factor_uplift"])
    weak = replace(dc, lines=(line(20, 34, voto=5.8, role="D"),))
    assert project(weak, bm=bm, prior=PRIOR_D, d_factor=TABLE).explain["d_factor_uplift"] == 0.0     # never a penalty
    striker_on = project(inputs(), bm=bm, d_factor=TABLE)
    assert striker_on.explain["d_factor_uplift"] == 0.0
    empty = DFactorTable((), False, None, None)
    assert project(dc, bm=bm, prior=PRIOR_D, d_factor=empty).explain["d_factor_uplift"] == 0.0


def test_the_d_factor_uplift_is_never_negative_even_from_a_non_monotonic_table(bm):
    # A hand-transcribed d_factor.yml (Task 10) could carry a lower-points
    # band above a higher-points one; the table's own slope would then be
    # negative around the 6.1 reference. The uplift must still floor at zero.
    non_monotonic = DFactorTable(bands=(Band(7.0, 6.0), Band(6.5, 1.0), Band(6.0, 5.0), Band(5.5, 0.0)),
                                 with_goalkeeper=False, source="synthetic", verified_on=date(2026, 8, 29))
    assert non_monotonic.slope(CFG.d_factor_reference) < 0    # the table really is non-monotonic here
    dc = inputs(player_id=2120, classic_role="D", roles=frozenset({Role.Dc}), role_class="Dc",
                lines=(line(20, 34, voto=6.6, role="D", events=Events()),))
    off = project(dc, bm=bm, prior=PRIOR_D)
    on = project(dc, bm=bm, prior=PRIOR_D, d_factor=non_monotonic)
    assert on.explain["d_factor_uplift"] == 0.0
    assert on.value_p25 == pytest.approx(off.value_p25)
    assert on.value_p25 >= 0


def test_role_flexibility_has_option_value(bm):
    single = project(inputs(roles=frozenset({Role.Pc})), bm=bm)
    double = project(inputs(roles=frozenset({Role.A, Role.Pc})), bm=bm)
    assert double.value_p50 == pytest.approx(single.value_p50 * (1 + CFG.flex_bonus_per_role))
    assert double.explain["flex_bonus"] == pytest.approx(1 + CFG.flex_bonus_per_role)


def test_giornate_remaining_scale_the_value(bm):
    full = project(inputs(), bm=bm, giornate_remaining=36)
    half = project(inputs(), bm=bm, giornate_remaining=18)
    assert half.exp_presenze == pytest.approx(full.exp_presenze / 2) and half.exp_fantamedia == full.exp_fantamedia


def test_project_all_uses_each_players_role_prior(bm):
    rows = project_all([inputs(), inputs(player_id=2120, classic_role="D", roles=frozenset({Role.Dc}), role_class="Dc",
                                         lines=())],
                       cfg=CFG, priors={"A": PRIOR_A, "D": PRIOR_D}, bm=bm, giornate_remaining=36, current_season=21)
    assert [p.player_id for p in rows] == [2764, 2120]
    assert rows[1].exp_fantamedia == pytest.approx(PRIOR_D.fantavoto_mean)
    assert CFG.to_dict()["season_weights"] == [1.0, 0.6, 0.35, 0.2]
