import json
from datetime import date

import pytest
from fantaclaude.cli.app import ExitCode, app
from fantaclaude.kb.audit import FrontMatterError, audit, parse_front_matter, ttl_days
from typer.testing import CliRunner

FM = "---\nupdated: {updated}\nttl: {ttl}\nconfidence: {confidence}\nsource: {source}\n---\n# doc\n"


def test_parse_front_matter_and_ttl():
    fm = parse_front_matter(FM.format(updated="2026-08-20", ttl="7d", confidence="high", source="regolamento"))
    assert fm.updated == date(2026, 8, 20) and fm.ttl == "7d" and fm.source == "regolamento"
    assert fm.raw["confidence"] == "high"
    assert parse_front_matter("# no front matter\n") is None
    assert ttl_days("30d") == 30 and ttl_days("never") is None
    with pytest.raises(FrontMatterError):
        ttl_days("soon")
    with pytest.raises(FrontMatterError):
        parse_front_matter("---\nupdated: 2026-08-20\n")            # unterminated
    with pytest.raises(FrontMatterError):
        parse_front_matter("---\nupdated: soon\n---\n")               # not a date


def test_audit_classifies_documents(tmp_path):
    kb = tmp_path / "kb"
    inter = kb / "serie-a" / "teams" / "inter"
    inter.mkdir(parents=True)
    (kb / "README.md").write_text("# the contract, not a document\n")
    (inter / "profile.md").write_text(FM.format(updated="2026-08-20", ttl="30d", confidence="high", source="web"))
    (inter / "news.md").write_text(FM.format(updated="2026-08-01", ttl="7d", confidence="low", source="web"))
    (inter / "bare.md").write_text("no front matter\n")
    (inter / "broken.md").write_text(FM.format(updated="2026-08-20", ttl="whenever", confidence="low", source="x"))
    (inter / "partial.md").write_text("---\nupdated: 2026-08-20\nttl: 7d\n---\n")
    (inter / "forever.md").write_text(FM.format(updated="2020-01-01", ttl="never", confidence="high", source="regolamento"))
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 24))}
    assert statuses == {
        "serie-a/teams/inter/bare.md": "missing_front_matter",
        "serie-a/teams/inter/broken.md": "invalid",
        "serie-a/teams/inter/forever.md": "ok",
        "serie-a/teams/inter/news.md": "expired",
        "serie-a/teams/inter/partial.md": "invalid",
        "serie-a/teams/inter/profile.md": "invalid",   # a profile needs the keys fantaclaude.kb.profiles validates
    }
    assert audit(tmp_path / "nowhere", date(2026, 8, 24)) == []


def test_audit_survives_an_unreadable_file(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "profile.md").write_text(FM.format(updated="2026-08-20", ttl="30d", confidence="high", source="web"))
    (kb / "garbled.md").write_bytes(b"\xff\xfe not utf-8")
    statuses = {e.path: e.status for e in audit(kb, date(2026, 8, 24))}
    assert statuses["garbled.md"] == "invalid"
    assert statuses["profile.md"] == "ok"


def test_audit_survives_malformed_front_matter_yaml(tmp_path):
    """A YAML syntax error is one document's problem, not the whole audit's."""
    kb = tmp_path / "kb" / "rules"
    kb.mkdir(parents=True)
    (kb / "good.md").write_text(FM.format(updated="2026-08-20", ttl="30d", confidence="high", source="admin"))
    (kb / "broken.md").write_text("---\nsource: [unclosed\nttl: 7d\nupdated: 2026-08-20\n---\n")
    statuses = {e.path: e.status for e in audit(tmp_path / "kb", date(2026, 8, 28))}
    assert statuses == {"rules/broken.md": "invalid", "rules/good.md": "ok"}


def test_updated_as_a_datetime_is_normalised_not_fatal(tmp_path):
    """PyYAML yields a datetime for `2026-08-20T10:00:00`, which is a `date`
    subclass -- so it passes the type check and then cannot be compared to one."""
    kb = tmp_path / "kb" / "rules"
    kb.mkdir(parents=True)
    (kb / "good.md").write_text(FM.format(updated="2026-08-20", ttl="30d", confidence="high", source="admin"))
    (kb / "stamped.md").write_text(
        FM.format(updated="2026-08-01T10:00:00", ttl="7d", confidence="high", source="admin"))
    statuses = {e.path: e.status for e in audit(tmp_path / "kb", date(2026, 8, 28))}
    assert statuses == {"rules/good.md": "ok", "rules/stamped.md": "expired"}
    fm = parse_front_matter(FM.format(updated="2026-08-20T10:00:00", ttl="7d",
                                      confidence="high", source="admin"))
    assert fm.updated == date(2026, 8, 20) and type(fm.updated) is date


def test_committed_tree_and_the_cli(monkeypatch, tmp_path):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import kb_dir

    root = kb_dir()
    assert (root / "README.md").is_file() and (root / "rules" / "aliases.yml").is_file()
    for sub in ("rules", "serie-a/teams", "league/participants", "league/history", "league/season-2026-27"):
        assert (root / sub).is_dir(), sub

    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    rules = tmp_path / "kb" / "rules"
    rules.mkdir(parents=True)
    (rules / "house-rules.md").write_text(FM.format(updated="2026-01-01", ttl="30d", confidence="high", source="admin"))
    result = CliRunner().invoke(app, ["kb", "audit", "--json", "--today", "2026-08-24"])
    assert result.exit_code == ExitCode.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["expired"] == 1 and payload["entries"][0]["path"] == "rules/house-rules.md"
    plain = CliRunner().invoke(app, ["kb", "audit", "--today", "2026-08-24"])
    assert plain.exit_code == ExitCode.OK and "expired" in plain.stdout and "house-rules.md" in plain.stdout


def test_kb_audit_rejects_a_malformed_today(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTACALCIO_HOME", str(tmp_path))
    result = CliRunner().invoke(app, ["kb", "audit", "--today", "banana"])
    assert result.exit_code == ExitCode.USAGE
    assert "banana" in result.stderr
