import os

import pytest
from fantaclaude.atomic import write_atomic


def test_write_atomic_replaces_the_file_whole_and_leaves_no_temp_behind(tmp_path):
    path = tmp_path / "deep" / "state.json"
    write_atomic(path, b'{"a": 1}')
    assert path.read_bytes() == b'{"a": 1}' and (path.stat().st_mode & 0o777) == 0o644
    write_atomic(path, b'{"a": 2}', mode=0o600)
    assert path.read_bytes() == b'{"a": 2}' and (path.stat().st_mode & 0o777) == 0o600
    assert sorted(p.name for p in path.parent.iterdir()) == ["state.json"]


def test_a_failed_replace_leaves_the_old_file_standing(tmp_path, monkeypatch):
    """The state file is the only record of what the room paid between the
    auction and the transfer: a crash mid-write must cost nothing."""
    path = tmp_path / "state.json"
    write_atomic(path, b"old")

    def boom(src, dst):
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_atomic(path, b"new")
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]       # the temp file is cleaned up too
