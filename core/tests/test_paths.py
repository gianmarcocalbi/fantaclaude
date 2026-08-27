from pathlib import Path

from fantaclaude import paths


def test_paths_follow_fantacalcio_home(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    assert paths.workspace_root() == tmp_path.resolve()
    assert paths.data_dir() == tmp_path.resolve() / "data"
    assert paths.raw_dir() == tmp_path.resolve() / "data" / "raw"
    assert paths.db_path() == tmp_path.resolve() / "data" / "fanta.duckdb"
    assert paths.kb_dir() == tmp_path.resolve() / "kb"
    assert paths.records_dir() == tmp_path.resolve() / "records"
    assert paths.league_yml_path() == tmp_path.resolve() / "league.yml"
    assert paths.preferences_yml_path() == tmp_path.resolve() / "preferences.yml"


def test_default_root_is_the_repository(monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    root = paths.workspace_root()
    assert (root / "mcp" / "fantacalcio").is_dir()
    assert (root / "core" / "src" / "fantaclaude").is_dir()
