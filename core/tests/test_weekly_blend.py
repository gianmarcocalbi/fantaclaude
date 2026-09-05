from datetime import datetime, timedelta
from pathlib import Path

from conftest import seed_news
from fantaclaude.analysis.weekly.blend import (
    SOURCE_NOTE,
    SOURCE_PUBLISHED,
    SOURCE_SQUALIFICATO,
    BlendLayer,
    blend,
    load_layer,
)
from fantaclaude.analysis.weekly.config import WEEKLY_VERSION, WeeklyConfig, weekly_hash
from fantaclaude.analysis.weekly.notes import NotesLayer
from fantaclaude.kb.audit import FrontMatter
from fantaclaude.kb.notes import PlayerNote

CFG = WeeklyConfig()
KICKOFF = datetime(2026, 9, 13, 16, 0)  # noqa: DTZ001 -- naive UTC, as DuckDB returns it


def _notes(**kw):
    return NotesLayer(4, (), kw.get("p_start", {}), kw.get("value_factor", {}), kw.get("excluded", {}), (), 0)


def _kb(player_id, *, depth=None, availability=1.0):
    return PlayerNote(Path("x.md"), player_id, "X", "INT", depth, availability, None,
                      FrontMatter(None, None, None, None, {}))


def _blend(layer, *, published=90, team="INT", exp_presenze=30.0, kickoff=KICKOFF):
    return blend(player_id=2764, name="Martinez L.", team_short=team, published=published, exp_presenze=exp_presenze,
                 kickoff=kickoff, layer=layer, cfg=CFG)


def test_the_page_is_the_base_and_the_trace_says_so():
    got = _blend(BlendLayer(4))
    assert (got.p_start, got.source, got.value_factor, got.excluded, got.warnings) == (0.9, SOURCE_PUBLISHED, 1.0, False, ())
    assert got.trace["published"] == 90 and got.trace["source"] == SOURCE_PUBLISHED and got.trace["checks"] == []


def test_a_squalifica_forces_zero_and_a_note_beats_it():
    layer = BlendLayer(4, squalificati={2764: "una giornata"})
    got = _blend(layer)
    assert (got.p_start, got.source) == (0.0, SOURCE_SQUALIFICATO) and got.trace["squalificato"] == "una giornata"
    overruled = _blend(BlendLayer(4, notes=_notes(p_start={2764: (0.5, "appeal accepted")}), squalificati={2764: "una giornata"}))
    assert (overruled.p_start, overruled.source) == (0.5, SOURCE_NOTE)
    assert overruled.trace["note"] == {"type": "p_start", "p_start": 0.5, "reason": "appeal accepted"}
    assert overruled.trace["squalificato"] == "una giornata"                     # carried, so the record says what was overruled


def test_a_value_note_and_an_exclusion_ride_in_the_trace_without_touching_p_start():
    got = _blend(BlendLayer(4, notes=_notes(value_factor={2764: (0.85, "knock")}, excluded={2764: "not this week"})))
    assert got.p_start == 0.9 and got.value_factor == 0.85 and got.excluded
    assert got.trace["value_factor"] == 0.85 and got.trace["value_note"] == "knock" and got.trace["excluded"] == "not this week"


def test_an_infortunato_the_page_still_prices_is_a_warning_and_the_number_survives():
    got = _blend(BlendLayer(4, infortunati={2764: "lesione al polpaccio, rientro a ottobre"}), published=55)
    assert got.p_start == 0.55 and got.source == SOURCE_PUBLISHED
    assert got.trace["checks"] == ["infortunato"] and "disagreement" in got.warnings[0] and "55%" in got.warnings[0]
    quiet = _blend(BlendLayer(4, infortunati={2764: "lesione"}), published=5)
    assert quiet.warnings == () and quiet.trace["infortunato"] == "lesione"          # below the threshold: carried, not argued


def test_a_kb_note_is_a_check_never_a_multiplier():
    out = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, depth="out")}))
    assert out.p_start == 0.9 and out.trace["checks"] == ["kb_depth_out"] and "depth 'out'" in out.warnings[0]
    thin = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, availability=0.6)}))
    assert thin.p_start == 0.9 and thin.trace["checks"] == ["kb_availability"] and "0.60" in thin.warnings[0]
    fine = _blend(BlendLayer(4, kb_notes={2764: _kb(2764, availability=0.8)}))
    assert fine.warnings == () and fine.p_start == 0.9


def test_a_european_tie_within_the_window_is_a_disagreement_not_a_fade():
    ties = (KICKOFF - timedelta(days=3), KICKOFF + timedelta(days=10))
    layer = BlendLayer(4, rotation={"INT": 0.7}, european={"INT": ties}, giornate_remaining=30)
    got = _blend(layer, published=90, exp_presenze=27.0)                            # season rate 0.9 x 0.7 = 0.63 vs 0.90
    assert got.p_start == 0.9 and got.trace["checks"] == ["european"] and "63%" in got.warnings[0]
    no_window = _blend(BlendLayer(4, rotation={"INT": 0.7}, european={"INT": (KICKOFF + timedelta(days=10),)},
                                  giornate_remaining=30), exp_presenze=27.0)
    assert no_window.warnings == ()
    not_rotating = _blend(BlendLayer(4, european={"INT": ties}, giornate_remaining=30), exp_presenze=27.0)
    assert not_rotating.warnings == ()
    low_published = _blend(layer, published=50, exp_presenze=27.0)
    assert low_published.warnings == ()


def test_checks_are_silent_once_a_note_or_a_squalifica_set_the_number():
    layer = BlendLayer(4, notes=_notes(p_start={2764: (1.0, "confirmed")}), infortunati={2764: "x"},
                       kb_notes={2764: _kb(2764, depth="out")})
    got = _blend(layer)
    assert got.warnings == () and got.trace["checks"] == [] and got.p_start == 1.0


def test_weekly_hash_moves_with_a_constant_and_not_otherwise():
    assert WEEKLY_VERSION == 1 and len(weekly_hash()) == 16 and weekly_hash() == weekly_hash(WeeklyConfig())
    assert weekly_hash(WeeklyConfig(european_gap=0.25)) != weekly_hash()


def test_load_layer_reads_the_news_the_notes_and_the_kb(db, tmp_path, fixture_json):
    import json
    from datetime import UTC

    from fantaclaude.ingest.listone_api import load_listone, record_listone
    from fantaclaude.ingest.raw import RawFile
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(fixture_json("listone_sample")), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-l", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    seed_news(db, 21, 4, "squalificati", [("squalificato", "Inter", "INT", "Martinez L.", 2764, "una giornata"),
                                          ("diffidato", "Inter", "INT", "Bastoni", 2120, "4 ammonizioni"),
                                          ("squalificato", "Bologna", None, "Orsolini", None, "due giornate")])
    seed_news(db, 21, 4, "infortunati", [("infortunato", "Roma", "ROM", "Dybala", 309, "affaticamento")])
    db.execute("INSERT INTO valuation_runs VALUES ('r', now(), 'h', 'm', 'i', 1, 1, 21, 3, ['balanced'], '{}'::JSON, ?::JSON)",
               [json.dumps({"giornate_remaining": 35})])
    notes = tmp_path / "lineup-notes.yml"
    notes.write_text("- {player: Kean, giornata: 4, type: exclude, reason: r}\n- {player: Kean, giornata: 5, type: exclude, reason: later}\n"
                     "- {player: Nobody, giornata: 4, type: exclude, reason: r}\n", encoding="utf-8")
    layer, warnings = load_layer(db, season_id=21, giornata=4, run_id="r", notes_path=notes, kb_dir=None, cfg=CFG)
    assert layer.squalificati == {2764: "una giornata"} and layer.diffidati == {2120: "4 ammonizioni"} and layer.infortunati == {309: "affaticamento"}
    assert layer.unmatched_news == 1 and set(layer.news_fetched) == {"squalificati", "infortunati"}
    assert layer.notes.excluded == {2097: "r"} and layer.notes.inert == 1 and layer.giornate_remaining == 35
    assert len(warnings) == 2                                                    # the inert note, and the unmatched Orsolini
    assert any("Nobody" in w for w in warnings) and any("matched nobody" in w for w in warnings)
    empty, warned = load_layer(db, season_id=21, giornata=5, run_id="r", notes_path=None, kb_dir=None, cfg=CFG)
    assert empty.squalificati == {} and any("ingest news" in w for w in warned)


def test_a_missing_squalificati_page_warns_even_when_infortunati_was_ingested(db, tmp_path, fixture_json):
    import json
    from datetime import UTC

    from fantaclaude.ingest.listone_api import load_listone, record_listone
    from fantaclaude.ingest.raw import RawFile
    path = tmp_path / "listone.json"
    path.write_text(json.dumps(fixture_json("listone_sample")), encoding="utf-8")
    record_listone(db, load_listone(path), RawFile(path, "sha-l", datetime(2026, 9, 4, tzinfo=UTC), "listone"))
    # Only `infortunati` was ingested for this giornata -- `fetched` is truthy, but no squalifica can force a zero.
    seed_news(db, 21, 4, "infortunati", [("infortunato", "Roma", "ROM", "Dybala", 309, "affaticamento")])
    layer, warnings = load_layer(db, season_id=21, giornata=4, run_id="r", notes_path=None, kb_dir=None, cfg=CFG)
    assert layer.squalificati == {} and set(layer.news_fetched) == {"infortunati"}
    assert any("squalificati" in w and "giornata 4" in w for w in warnings)
    assert not any("infortunati page" in w for w in warnings)                # infortunati *was* fetched -- no warning about it
