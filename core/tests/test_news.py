import json
from datetime import UTC, datetime

import pytest
from conftest import FIXTURE_DIR
from fantaclaude.ingest.news import (
    PAGES,
    NewsShapeError,
    parse_news_page,
    record_news,
    source_of,
)
from fantaclaude.ingest.raw import RawFile

INJURIES = (FIXTURE_DIR / "news_infortunati_sample.html").read_text(encoding="utf-8")
SUSPENSIONS = (FIXTURE_DIR / "news_squalificati_sample.html").read_text(encoding="utf-8")
EMPTY = '<div class="empty-list-message">Nessuno</div>'
ENTRY = ('<ul class="unstyled"><li><strong class="item-name">{name}</strong>'
         '<div class="item-description"><p>{detail}</p></div></li></ul>')


def test_the_injuries_page_lists_every_entry_under_its_club():
    page = parse_news_page(INJURIES, page="infortunati")
    assert page.page == "infortunati" and page.teams == 2 and page.empty_lists == 0
    assert [(r.team_name, r.name, r.kind) for r in page.rows] == [
        ("Atalanta", "Sulemana K.", "infortunato"), ("Atalanta", "Hien", "infortunato"),
        ("Bologna", "Orsolini", "infortunato"), ("Bologna", "El Azzouzi O.", "infortunato")]
    assert [r.position for r in page.rows] == [0, 1, 2, 3]
    assert "ottobre" in page.rows[0].detail and "<p>" not in page.rows[0].detail      # text, tags stripped
    assert page.rows[0].raw == {"team": "Atalanta", "label": None}


def test_the_suspensions_page_with_empty_columns_is_a_page_with_no_rows():
    page = parse_news_page(SUSPENSIONS, page="squalificati")
    assert page.rows == [] and page.teams == 2 and page.empty_lists == 4


def test_a_suspension_and_a_diffida_are_read_under_their_column_labels():
    # the entry shape is INFERRED from the injuries page (the capture had none): Task 12 confirms it
    text = SUSPENSIONS.replace(EMPTY, ENTRY.format(name="Kolasinac", detail="Una giornata"), 1)
    text = text.replace(EMPTY, ENTRY.format(name="Hien", detail="Quarta ammonizione"), 1)
    page = parse_news_page(text, page="squalificati")
    assert [(r.team_name, r.name, r.kind, r.detail) for r in page.rows] == [
        ("Atalanta", "Kolasinac", "squalificato", "Una giornata"), ("Atalanta", "Hien", "diffidato", "Quarta ammonizione")]
    assert page.empty_lists == 2 and page.rows[0].raw["label"] == "Squalificati"


def test_a_page_without_club_cards_fails_loud_and_names_the_selector():
    with pytest.raises(NewsShapeError, match="team-card"):
        parse_news_page("<html><body><h1>Infortunati Serie A</h1></body></html>", page="infortunati")


def test_a_suspensions_page_without_labels_fails_loud():
    unlabelled = SUSPENSIONS.replace('class="label label-danger"', 'class="tag"').replace('class="label label-warn"', 'class="tag"')
    with pytest.raises(NewsShapeError, match="label"):
        parse_news_page(unlabelled, page="squalificati")


def test_an_unknown_label_fails_loud_rather_than_guessing_a_kind():
    with pytest.raises(NewsShapeError, match="Infortunati lunghi"):
        parse_news_page(SUSPENSIONS.replace(">Diffidati<", ">Infortunati lunghi<", 1), page="squalificati")


def test_an_entry_under_no_label_on_the_suspensions_page_is_refused():
    # strip the first column's header, leaving an entry under nothing
    text = SUSPENSIONS.replace('<header>\n                    <strong class="label label-danger">Squalificati</strong>\n                </header>', "", 1)
    text = text.replace(EMPTY, ENTRY.format(name="Kolasinac", detail="Una giornata"), 1)
    with pytest.raises(NewsShapeError, match="no label"):
        parse_news_page(text, page="squalificati")


def test_the_match_widget_outside_the_cards_is_not_a_club():
    # the `#team-menu` jump-list above the cards repeats every club as `li.team-item`
    # anchors (`data-team="atalanta"`, no `team-name` span) -- on the real capture this
    # is the widget the brief's docstring describes, not a `team-name team-link` anchor;
    # either way it must not become a twenty-first club
    page = parse_news_page(INJURIES, page="infortunati")
    assert page.teams == 2 and INJURIES.count('class="team-item"') > 0


def _raw(tmp_path, text: str, page: str, stamp: str = "1") -> RawFile:
    path = tmp_path / f"news-{page}-{stamp}.html"
    path.write_text(text, encoding="utf-8")
    return RawFile(path, f"sha-{page}-{stamp}", datetime(2026, 9, 5, 12, 0, tzinfo=UTC), "news")


def _aliases(tmp_path):
    path = tmp_path / "aliases.yml"
    path.write_text("understat: {}\nfantacalcio_teams: {}\n", encoding="utf-8")
    return path


def test_record_appends_a_file_and_its_rows_and_dedupes_on_bytes(db, tmp_path):
    page = parse_news_page(INJURIES, page="infortunati")
    first = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati"), aliases_path=_aliases(tmp_path))
    assert not first.skipped_duplicate and first.inserted == 4 and first.teams == 2
    assert first.unmatched == 4 and first.unknown_teams == 2          # no listone: every club and name unknown
    assert db.execute("SELECT kind, source, row_count, unmatched FROM news_files").fetchone() == (
        "infortunati", source_of("infortunati"), 4, 4)
    assert db.execute("SELECT kind, team_name, team_short, name, player_id, match_status FROM unavailable ORDER BY position").fetchall()[0] == (
        "infortunato", "Atalanta", None, "Sulemana K.", None, "unmatched")
    again = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati"), aliases_path=_aliases(tmp_path))
    assert again.skipped_duplicate and again.file_id == first.file_id and again.inserted == 0
    later = record_news(db, 21, 4, page, _raw(tmp_path, INJURIES, "infortunati", stamp="2"), aliases_path=_aliases(tmp_path))
    assert later.file_id != first.file_id
    assert db.execute("SELECT file_id FROM v_news_files_current WHERE kind = 'infortunati'").fetchone()[0] == later.file_id
    assert db.execute("SELECT count(*) FROM v_unavailable_current").fetchone()[0] == 4


def test_record_matches_names_within_the_club_and_flags_the_rest(db, tmp_path, fixture_json):
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    listone = fixture_json("listone_sample")
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(listone), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    # Atalanta is in the fixture listone (Kolasinac 2640, Rossi F. * 2297); Bologna is not
    text = INJURIES.replace("Sulemana K.", "Kolasinac", 1)
    page = parse_news_page(text, page="infortunati")
    result = record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati"), aliases_path=_aliases(tmp_path))
    rows = db.execute("SELECT name, team_short, player_id, match_status FROM unavailable ORDER BY position").fetchall()
    assert rows == [("Kolasinac", "ATA", 2640, "matched"), ("Hien", "ATA", None, "unmatched"),
                    ("Orsolini", None, None, "unmatched"), ("El Azzouzi O.", None, None, "unmatched")]
    assert result.unmatched == 3 and result.unknown_teams == 1


def test_record_never_matches_a_name_across_clubs(db, tmp_path, fixture_json):
    """Kolasinac is Atalanta's in the listone; listed under Bologna he must
    stay unmatched rather than be found by surname across the league."""
    from fantaclaude.ingest.listone_api import load_listone, record_listone
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(fixture_json("listone_sample")), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-listone", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    (tmp_path / "aliases.yml").write_text("understat: {}\nfantacalcio_teams: {Bologna: Atalanta}\n", encoding="utf-8")
    text = INJURIES.replace("Orsolini", "Kolasinac", 1)
    page = parse_news_page(text, page="infortunati")
    record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati"), aliases_path=tmp_path / "aliases.yml")
    # with the alias, "Bologna" resolves to ATA and Kolasinac matches there -- the alias is the operator's call, not the adapter's
    assert db.execute("SELECT team_short, player_id FROM unavailable WHERE name = 'Kolasinac'").fetchone() == ("ATA", 2640)
    (tmp_path / "aliases.yml").write_text("understat: {}\nfantacalcio_teams: {}\n", encoding="utf-8")
    record_news(db, 21, 4, page, _raw(tmp_path, text, "infortunati", stamp="2"), aliases_path=tmp_path / "aliases.yml")
    assert db.execute("SELECT team_short, player_id FROM v_unavailable_current WHERE name = 'Kolasinac'").fetchone() == (None, None)


def test_pages_are_the_two_the_spec_names():
    assert PAGES == ("squalificati", "infortunati")
