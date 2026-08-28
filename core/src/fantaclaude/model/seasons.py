"""Season identifiers across the sources, anchored on one verified pair.

The league API numbers seasons: season_id 21 is 2026-27 -- observed in the
league status (sId 21, 2026-08-22) and on the public voti page, whose title
says "stagione 2026/27" and whose Excel link is /api/v1/Excel/votes/21/1
(2026-08-28). Understat names a season by its starting year (2026), UEFA by
its ending year (seasonYear=2027). One anchor and an offset, so no season is
hardcoded anywhere else.
"""

from __future__ import annotations

SEASON_ID_ANCHOR = 21
START_YEAR_ANCHOR = 2026
SERIE_A_GIORNATE = 38           # the competition's format, not a league rule


def start_year(season_id: int) -> int:
    return START_YEAR_ANCHOR + (season_id - SEASON_ID_ANCHOR)


def season_label(season_id: int) -> str:
    """'2026-27' -- the spelling fantacalcio.it uses in URLs and titles."""
    year = start_year(season_id)
    return f"{year}-{(year + 1) % 100:02d}"


def season_id_from_label(label: str) -> int:
    """Inverse of season_label; ValueError on anything else."""
    head, sep, tail = label.partition("-")
    if not sep or len(head) != 4 or len(tail) != 2 or not (head + tail).isdigit():
        raise ValueError(f"not a season label like '2026-27': {label!r}")
    year = int(head)
    if (year + 1) % 100 != int(tail):
        raise ValueError(f"season label years do not follow each other: {label!r}")
    return SEASON_ID_ANCHOR + (year - START_YEAR_ANCHOR)


def understat_season(season_id: int) -> int:
    return start_year(season_id)


def uefa_season_year(season_id: int) -> int:
    return start_year(season_id) + 1


def back_seasons(current: int, n: int = 3) -> list[int]:
    """The n seasons before `current`, oldest first: back_seasons(21) == [18, 19, 20]."""
    return [current - i for i in range(n, 0, -1)]
