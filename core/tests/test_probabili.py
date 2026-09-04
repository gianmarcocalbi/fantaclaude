import re
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR
from fantaclaude.ingest.probabili import (
    SOURCE,
    ProbabiliShapeError,
    parse_probabili_page,
    record_probabili,
)
from fantaclaude.ingest.raw import RawFile

SAMPLE = (FIXTURE_DIR / "probabili_sample.html").read_text(encoding="utf-8")


def test_parse_reads_every_player_with_his_listone_id_and_percentage():
    page = parse_probabili_page(SAMPLE)
    assert page.matches == 2 and page.uncompiled == 0 and page.duplicates == 0
    clubs = {r.club_slug for r in page.rows}
    assert len(clubs) == 4
    assert all(0 <= r.p_start <= 100 for r in page.rows)
    assert all(isinstance(r.player_id, int) and r.name for r in page.rows)
    assert all(r.updated_at is not None and r.updated_at.tzinfo is UTC for r in page.rows)
    assert {r.bench for r in page.rows} == {True, False}          # starters and panchina both listed
    first = page.rows[0]
    assert (first.player_id, first.name, first.p_start) == (7332, "Bijlow", 90)   # from the fixture: Genoa's Bijlow
    assert sorted({r.updated_at for r in page.rows}) == [datetime(2026, 9, 4, 9, 5, tzinfo=UTC),   # genoa-como
                                                         datetime(2026, 9, 4, 11, 4, tzinfo=UTC)]  # fiorentina-torino


def test_parse_reads_the_giornata_from_the_match_microdata():
    # the visible text never names the giornata on this layout; only
    # <meta itemprop="name" content="Serie A 2026-27 - 3° giornata - genoa-como" /> does
    page = parse_probabili_page(SAMPLE)
    assert page.giornata == 3


def test_parse_carries_each_clubs_formation_as_context():
    page = parse_probabili_page(SAMPLE)
    by_club = {r.club_slug: r.formation for r in page.rows}
    assert all(f and re.fullmatch(r"\d{3,4}", f) for f in by_club.values())
    # pinned against the fixture: each club-lineup widget's own data-formation
    assert by_club == {"genoa": "352", "como": "4231", "fiorentina": "4321", "torino": "3421"}


def test_an_uncompiled_match_is_skipped_and_counted_not_fatal():
    # strip every player of the second match: the page still has two match headers
    page = parse_probabili_page(SAMPLE)
    second = {r.club_slug for r in page.rows if r.updated_at == max(x.updated_at for x in page.rows)}
    text = SAMPLE
    for slug in second:
        text = re.sub(rf'<li[^>]*player-item[^>]*>(?:(?!</li>).)*?/serie-a/squadre/{slug}/(?:(?!</li>).)*?</li>', "", text, flags=re.DOTALL)
    stripped = parse_probabili_page(text)
    assert stripped.matches == 1 and stripped.uncompiled == 1
    assert {r.club_slug for r in stripped.rows} == {r.club_slug for r in page.rows} - second


def test_a_page_without_players_fails_loud_and_names_the_selector():
    with pytest.raises(ProbabiliShapeError, match="player-item"):
        parse_probabili_page("<html><body><p>Probabili formazioni</p></body></html>")


def test_a_percentage_that_is_not_a_number_fails_loud():
    text = SAMPLE.replace('aria-valuenow="', 'aria-valuenow="x', 1)
    with pytest.raises(ProbabiliShapeError, match="aria-valuenow"):
        parse_probabili_page(text)


def _raw(tmp_path, text: str, stamp: str = "1") -> RawFile:
    path = tmp_path / f"probabili-{stamp}.html"
    path.write_text(text, encoding="utf-8")
    return RawFile(path, f"sha-{stamp}", datetime(2026, 9, 4, 12, 0, tzinfo=UTC), "probabili")


def test_record_appends_a_file_and_its_rows_and_dedupes_on_bytes(db, tmp_path):
    page = parse_probabili_page(SAMPLE)
    first = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert not first.skipped_duplicate and first.inserted == len(page.rows) and first.matches == 2
    assert first.unknown_players == len(page.rows)               # no listone in this database: every id unknown
    assert db.execute("SELECT source, row_count FROM probabili_files").fetchone() == (SOURCE, len(page.rows))
    again = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert again.skipped_duplicate and again.file_id == first.file_id and again.inserted == 0
    later = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE, stamp="2"))
    assert later.file_id != first.file_id                         # a Friday re-compilation is a later file
    assert db.execute("SELECT file_id FROM v_probabili_files_current WHERE giornata = 3").fetchone()[0] == later.file_id
    assert db.execute("SELECT count(*) FROM v_probabili_current").fetchone()[0] == len(page.rows)


def test_record_resolves_team_short_from_the_listone(db, tmp_path, fixture_json):
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    from fantaclaude.ingest.raw import RawFile as RF
    listone = fixture_json("listone_sample")
    path = tmp_path / "listone.json"
    path.write_text(__import__("json").dumps(listone), encoding="utf-8")
    record_listone(db, load_listone(path), RF(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    page = parse_probabili_page(SAMPLE)
    known = {r[0] for r in db.execute("SELECT player_id FROM v_players_current").fetchall()}
    result = record_probabili(db, 21, 3, page, _raw(tmp_path, SAMPLE))
    assert result.unknown_players == sum(1 for r in page.rows if r.player_id not in known)
    resolved = db.execute("SELECT count(*) FROM probabili WHERE team_short IS NOT NULL").fetchone()[0]
    assert resolved == len(page.rows) - result.unknown_players
