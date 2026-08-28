import pytest
from fantaclaude.model.seasons import (
    SERIE_A_GIORNATE,
    back_seasons,
    season_id_from_label,
    season_label,
    start_year,
    uefa_season_year,
    understat_season,
)


def test_anchor_and_offsets():
    assert start_year(21) == 2026 and start_year(18) == 2023
    assert season_label(21) == "2026-27" and season_label(18) == "2023-24"
    assert understat_season(21) == 2026 and understat_season(20) == 2025
    assert uefa_season_year(21) == 2027 and uefa_season_year(20) == 2026
    assert back_seasons(21) == [18, 19, 20] and back_seasons(21, 1) == [20]
    assert SERIE_A_GIORNATE == 38


def test_label_round_trips_and_rejects_garbage():
    for season_id in (17, 21, 25):
        assert season_id_from_label(season_label(season_id)) == season_id
    for bad in ("2026", "2026-28", "26-27", "banana", "2026/27"):
        with pytest.raises(ValueError):
            season_id_from_label(bad)
