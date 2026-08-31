import pytest
from fantaclaude.yamlio import YamlFileError, read_yaml_mapping


def test_read_yaml_mapping_reads_a_mapping_and_names_every_way_a_file_can_be_wrong(tmp_path):
    path = tmp_path / "x.yml"
    path.write_text("a: 1\nb: [1, 2]\n", encoding="utf-8")
    assert read_yaml_mapping(path) == {"a": 1, "b": [1, 2]}
    path.write_text("", encoding="utf-8")
    assert read_yaml_mapping(path) == {}
    for text, match in (("- a list\n", "top level must be a mapping"), ("a: [\n", "x.yml")):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(YamlFileError, match=match):
            read_yaml_mapping(path)
    with pytest.raises(YamlFileError, match="missing"):
        read_yaml_mapping(tmp_path / "missing.yml")
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(YamlFileError, match="x.yml"):
        read_yaml_mapping(path)
