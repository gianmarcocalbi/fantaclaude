import pytest
from fantaclaude.ingest.listone_api import load_listone, record_listone
from fantaclaude.ingest.names import (
    ALIAS,
    AMBIGUOUS,
    MATCHED,
    UNMATCHED,
    AliasError,
    Candidate,
    Matcher,
    load_aliases,
    load_candidates,
    load_teams,
    normalise,
    resolve_team,
    split_listone_name,
)
from fantaclaude.ingest.raw import RawStore


def test_normalise_strips_accents_and_punctuation():
    assert normalise("Rasmus Højlund") == ["rasmus", "hojlund"]
    assert normalise("Lautaro Martínez") == ["lautaro", "martinez"]
    assert normalise("M'Bala Nzola") == ["m", "bala", "nzola"]
    assert normalise("Bodø/Glimt") == ["bodo", "glimt"]
    assert normalise("Konè M.") == ["kone", "m"]
    assert normalise("  Łukasz  Skorupski ") == ["lukasz", "skorupski"]
    assert normalise("") == []


def test_split_listone_name():
    assert split_listone_name("Martinez L.") == (["martinez"], "l")
    assert split_listone_name("Pellegrini Lo.") == (["pellegrini"], "lo")
    assert split_listone_name("Esposito F.P.") == (["esposito"], "fp")
    assert split_listone_name("Ederson D.S.") == (["ederson"], "ds")
    assert split_listone_name("Thuram") == (["thuram"], None)
    assert split_listone_name("Rossi F. *") == (["rossi"], "f")
    assert split_listone_name("Carlos Augusto") == (["carlos", "augusto"], None)
    assert split_listone_name("De Bruyne") == (["de", "bruyne"], None)


CANDIDATES = [
    Candidate(2764, "Martinez L.", "INT", "Inter"),
    Candidate(5116, "Martinez Jo.", "INT", "Inter"),
    Candidate(4871, "Thuram", "INT", "Inter"),
    Candidate(5562, "Thuram K.", "JUV", "Juventus"),
    Candidate(6052, "Hojlund", "NAP", "Napoli"),
    Candidate(530, "Pellegrini Lo.", "ROM", "Roma"),
    Candidate(2728, "Pellegrini Lu.", "LAZ", "Lazio"),
    Candidate(6024, "Sulemana I.", "ATA", "Atalanta"),
    Candidate(5918, "Sulemana K.", "ATA", "Atalanta"),
    Candidate(2815, "Terracciano", "MIL", "Milan"),
    Candidate(5812, "Terracciano F.", "MIL", "Milan"),
    Candidate(7000, "Konè M.", "ROM", "Roma"),
    Candidate(7001, "Kone B.", "ATA", "Atalanta"),
    Candidate(7002, "Konè I.", "ROM", "Roma"),
    Candidate(2517, "De Bruyne", "NAP", "Napoli"),
    Candidate(5877, "Carlos Augusto", "INT", "Inter"),
    Candidate(5792, "Ederson D.S.", "ATA", "Atalanta"),
    Candidate(7003, "Esposito Se.", "CAG", "Cagliari"),
    Candidate(7004, "Esposito F.P.", "INT", "Inter"),
    Candidate(7005, "Dumfries", "INT", "Inter"),
    Candidate(2120, "Bastoni A.", "INT", "Inter"),
]


@pytest.mark.parametrize("source, teams, status, player_id", [
    ("Lautaro Martínez", ("INT",), MATCHED, 2764),        # initial decides
    ("Josep Martínez", ("INT",), MATCHED, 5116),          # two-letter initial is a prefix of the given name
    ("Marcus Thuram", ("INT",), MATCHED, 4871),           # bare surname is compatible; K. is not
    ("Khephren Thuram", ("JUV",), MATCHED, 5562),
    ("Rasmus Højlund", ("NAP",), MATCHED, 6052),          # accent folding
    ("Lorenzo Pellegrini", ("ROM",), MATCHED, 530),
    ("Sulemana", ("BOL", "CAG"), AMBIGUOUS, None),        # no given name, club does not help
    ("Ibrahim Sulemana", ("ATA",), MATCHED, 6024),
    ("Pietro Terracciano", ("MIL",), MATCHED, 2815),      # F. excluded, bare surname stays
    ("Filippo Terracciano", (), AMBIGUOUS, None),         # F. and the bare surname both fit; no club
    ("Kouadio Kone", ("ROM",), AMBIGUOUS, None),          # the given name contradicts every initial
    ("Kevin De Bruyne", ("NAP",), MATCHED, 2517),         # multi-token surname
    ("Carlos Augusto", ("INT",), MATCHED, 5877),          # the whole source name is the surname
    ("Ederson", ("ATA",), MATCHED, 5792),                 # mononym, initials ignored
    ("Francesco Pio Esposito", ("INT",), MATCHED, 7004),  # F.P. = initials of two given names
    ("Sebastiano Esposito", ("CAG",), MATCHED, 7003),
    ("Denzel Dumfries", ("INT",), MATCHED, 7005),
    ("Jamie Vardy", ("CRE",), UNMATCHED, None),
    ("Khvicha Hojlund", ("NAP",), MATCHED, 6052),      # a lone candidate without an initial fits any given name
    ("Josep Bastoni", ("INT",), AMBIGUOUS, None),       # a lone candidate whose initial contradicts the given name does not
    ("", (), UNMATCHED, None),
])
def test_matcher_cases(source, teams, status, player_id):
    result = Matcher(CANDIDATES).match(source, teams)
    assert (result.status, result.player_id) == (status, player_id), result


def test_matcher_reports_candidates_and_honours_aliases():
    matcher = Matcher(CANDIDATES, aliases={"Sulemana": 5918, "Kouadio Kone": 7000})
    ambiguous = Matcher(CANDIDATES).match("Sulemana", ("BOL",))
    assert ambiguous.status == AMBIGUOUS and set(ambiguous.candidates) == {6024, 5918}
    assert matcher.match("Sulemana", ("BOL",)) == Matcher(CANDIDATES, {"Sulemana": 5918}).match("Sulemana")
    assert matcher.match("Sulemana").status == ALIAS and matcher.match("Sulemana").player_id == 5918
    assert matcher.match("Kouadio Kone").player_id == 7000
    with pytest.raises(AliasError, match="999999"):
        Matcher(CANDIDATES, aliases={"Nobody": 999999})           # an alias must point at a listone id


def test_resolve_team_is_case_insensitive_and_alias_aware():
    teams = {"milan": "MIL", "parma": "PAR", "inter": "INT"}
    aliases = {"AC Milan": "Milan", "Parma Calcio 1913": "Parma"}
    assert resolve_team("Inter", teams, aliases) == "INT"
    assert resolve_team("inter ", teams, aliases) == "INT"
    assert resolve_team("AC Milan", teams, aliases) == "MIL"
    assert resolve_team("Parma Calcio 1913", teams, aliases) == "PAR"
    assert resolve_team("Cremonese", teams, aliases) is None


def test_load_aliases_validates_shapes(tmp_path):
    path = tmp_path / "aliases.yml"
    path.write_text("understat:\n  Marcus Thuram: 4871\nunderstat_teams:\n  AC Milan: Milan\nuefa_teams: {}\n")
    aliases = load_aliases(path)
    assert aliases.players == {"understat": {"Marcus Thuram": 4871}}
    assert aliases.teams == {"understat": {"AC Milan": "Milan"}, "uefa": {}}
    path.write_text("understat:\n  Marcus Thuram: Thuram\n")
    with pytest.raises(AliasError, match="listone id"):
        load_aliases(path)
    path.write_text("understat_teams:\n  AC Milan: 12\n")
    with pytest.raises(AliasError, match="team name"):
        load_aliases(path)
    path.write_text("- not a mapping\n")
    with pytest.raises(AliasError):
        load_aliases(path)
    path.write_text("")
    assert load_aliases(path).players == {} and load_aliases(path).teams == {}


def test_committed_aliases_file_parses(monkeypatch):
    monkeypatch.delenv("FANTACALCIO_HOME", raising=False)
    from fantaclaude.paths import aliases_path

    aliases = load_aliases(aliases_path())
    assert aliases.teams["understat"] == {"AC Milan": "Milan", "Parma Calcio 1913": "Parma"}
    assert "understat" in aliases.players and {"uefa", "fantacalcio"} <= set(aliases.teams)


def test_candidates_and_teams_come_from_the_current_listone(db, tmp_path, fixture_json):
    store = RawStore(tmp_path / "raw")
    raw = store.write("listone", fixture_json("listone_sample"))
    record_listone(db, load_listone(raw.path), raw)
    candidates = {c.player_id: c for c in load_candidates(db)}
    assert len(candidates) == 17 and candidates[2764].name == "Martinez L."
    assert candidates[2764].surname == "martinez" and candidates[2764].initial == "l"
    assert candidates[2764].team_short == "INT" and candidates[2764].team_name == "Inter"
    teams = load_teams(db)
    assert teams["inter"] == "INT" and teams["atalanta"] == "ATA"
    assert Matcher(load_candidates(db)).match("Lautaro Martínez", ("INT",)).player_id == 2764
