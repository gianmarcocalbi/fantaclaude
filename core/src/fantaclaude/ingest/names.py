"""Name matching across sources, and the aliases that override it.

fantacalcio.it writes "Martinez L." and "Pellegrini Lo."; Understat writes
"Lautaro Martínez" and "Lorenzo Pellegrini". The listone is the identity
(player_id); every other source is matched onto it -- surname first, then
the initial, then the club -- and a human alias in kb/rules/aliases.yml
beats all three. A row that cannot be decided is flagged with its
candidates, never dropped and never guessed: a wrong join is worse than a
missing one, because nothing downstream would notice it.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import yaml

MATCHED, ALIAS, AMBIGUOUS, UNMATCHED = "matched", "alias", "ambiguous", "unmatched"

# Letters NFKD does not decompose, plus the punctuation that splits a name.
_EXTRA = str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
                        "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
                        "'": " ", "’": " ", "-": " ", "/": " "})


def normalise(text: str) -> list[str]:
    """Lower-case ASCII tokens: accents stripped, punctuation to spaces."""
    text = unicodedata.normalize("NFKD", text.translate(_EXTRA))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch if ch.isalpha() else " " for ch in text.lower()).split()


def split_listone_name(name: str) -> tuple[list[str], str | None]:
    """"Pellegrini Lo." -> (["pellegrini"], "lo"); "Thuram" -> (["thuram"], None).

    A part ending in "." is an initial (the listone's way of telling two
    surnames apart); "*" is the transfer flag, not a name."""
    surname: list[str] = []
    initials: list[str] = []
    for part in name.replace("*", " ").split():
        (initials if part.endswith(".") else surname).extend(normalise(part))
    return surname, ("".join(initials) or None)


@dataclass(frozen=True)
class Candidate:
    player_id: int
    name: str                    # as the listone writes it
    team_short: str
    team_name: str

    @property
    def surname(self) -> str:
        return " ".join(split_listone_name(self.name)[0])

    @property
    def initial(self) -> str | None:
        return split_listone_name(self.name)[1]


@dataclass(frozen=True)
class Match:
    player_id: int | None
    status: str                          # matched | alias | ambiguous | unmatched
    candidates: tuple[int, ...] = ()     # listone ids that share the surname


class AliasError(ValueError):
    """aliases.yml is malformed or names an id the listone does not have."""


def _compatible(candidate: Candidate, given: list[str]) -> bool:
    """Does the listone initial fit the source's given name(s)?"""
    initial = candidate.initial
    if initial is None or not given:
        return True
    acronym = "".join(token[0] for token in given)
    return given[0].startswith(initial) or acronym.startswith(initial)


class Matcher:
    def __init__(self, candidates: list[Candidate], aliases: dict[str, int] | None = None) -> None:
        self._by_surname: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            self._by_surname.setdefault(candidate.surname, []).append(candidate)
        ids = {c.player_id for c in candidates}
        self._aliases = dict(aliases or {})
        unknown = sorted(str(v) for v in self._aliases.values() if v not in ids)
        if unknown:
            raise AliasError(f"aliases name listone ids that do not exist: {', '.join(unknown)}")

    def match(self, source_name: str, source_teams: tuple[str, ...] = ()) -> Match:
        alias = self._aliases.get(source_name)
        if alias is not None:
            return Match(alias, ALIAS, (alias,))
        tokens = normalise(source_name)
        found: list[Candidate] = []
        split_at = 0
        for split_at in range(len(tokens)):
            found = self._by_surname.get(" ".join(tokens[split_at:]), [])
            if found:
                break
        if not found:
            return Match(None, UNMATCHED)
        ids = tuple(c.player_id for c in found)
        # The initial is checked even for a lone candidate: with a partial
        # listone, "Josep Martínez" must not silently become "Martinez L.".
        given = tokens[:split_at]
        narrowed = [c for c in found if _compatible(c, given)]
        if given and not narrowed:
            return Match(None, AMBIGUOUS, ids)          # the given name contradicts every initial
        if len(narrowed) == 1:
            return Match(narrowed[0].player_id, MATCHED, ids)
        by_club = [c for c in narrowed if c.team_short in set(source_teams)]
        if len(by_club) == 1:
            return Match(by_club[0].player_id, MATCHED, ids)
        return Match(None, AMBIGUOUS, ids)


def match_listone(name: str, candidates: list[Candidate]) -> Match:
    """Match a name already written the listone's way -- surname first, then
    the initial that tells two of them apart -- against the listone.

    `Matcher.match` cannot do this: it is built for the sources that put the
    given name first, so it walks *suffixes* of the tokens and reads the
    trailing initial of "Adams A." as the surname. A name the listone spells
    character for character comes back unmatched. The knowledge base writes
    its takers the listone's way, so it needs this door instead. Several
    players of the surname and none of them are told apart, because they ask
    the reader for different things."""
    surname, initial = split_listone_name(name)
    found = [c for c in candidates if split_listone_name(c.name)[0] == surname] if surname else []
    if not found:
        return Match(None, UNMATCHED)
    ids = tuple(c.player_id for c in found)
    # When the name omits the initial, only a candidate the listone itself does not
    # distinguish (no initial of its own) is a safe match: a lone "Martinez" must not
    # silently become "Martinez L." when the listone bothered to write the "L.".
    # When the name gives an initial, an exact match wins; short of that, a bare
    # surname is a safe fallback only when it is the *sole* candidate at all -- not
    # whenever some other, differently-initialled player happens to share the surname
    # and lack an initial of their own. Otherwise a typo'd initial ("Terracciano X.")
    # would silently match the wrong player instead of failing to match anyone.
    if initial is None:
        narrowed = [c for c in found if c.initial is None]
    else:
        exact = [c for c in found if c.initial == initial]
        narrowed = exact if exact else (found if len(found) == 1 else [])
    if len(narrowed) == 1:
        return Match(narrowed[0].player_id, MATCHED, ids)
    if narrowed or initial is None:
        return Match(None, AMBIGUOUS, ids)
    return Match(None, UNMATCHED, ids)


def resolve_team(source_name: str, teams: dict[str, str], aliases: dict[str, str]) -> str | None:
    """`teams`: lower-cased listone team name -> short code; `aliases`: the
    source's spelling -> the listone's name. None when the club is not in
    the listone (a relegated side in a back season, a foreign club)."""
    name = aliases.get(source_name.strip(), source_name)
    return teams.get(name.strip().lower())


def load_candidates(con: duckdb.DuckDBPyConnection) -> list[Candidate]:
    rows = con.execute(
        "SELECT player_id, name, team_short, team_name FROM v_players_current ORDER BY player_id").fetchall()
    return [Candidate(int(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]


def load_teams(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return {str(name).lower(): str(short)
            for name, short in con.execute("SELECT name, short FROM v_teams_current").fetchall()}


@dataclass(frozen=True)
class Aliases:
    players: dict[str, dict[str, int]] = field(default_factory=dict)   # source -> spelling -> player_id
    teams: dict[str, dict[str, str]] = field(default_factory=dict)     # source -> spelling -> listone name

    def players_for(self, source: str) -> dict[str, int]:
        return self.players.get(source, {})

    def teams_for(self, source: str) -> dict[str, str]:
        return self.teams.get(source, {})


def load_aliases(path: Path) -> Aliases:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise AliasError(f"{path}: the top level must be a mapping of sources")
    players: dict[str, dict[str, int]] = {}
    teams: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        value = value or {}
        if not isinstance(value, dict):
            raise AliasError(f"{path}: {key} must be a mapping")
        if str(key).endswith("_teams"):
            bad = [k for k, v in value.items() if not isinstance(v, str)]
            if bad:
                raise AliasError(f"{path}: {key}: a team alias maps to a listone team name, not {bad}")
            teams[str(key).removesuffix("_teams")] = {str(k): v for k, v in value.items()}
        else:
            bad = [k for k, v in value.items() if isinstance(v, bool) or not isinstance(v, int)]
            if bad:
                raise AliasError(f"{path}: {key}: a player alias maps to a listone id, not {bad}")
            players[str(key)] = {str(k): v for k, v in value.items()}
    return Aliases(players, teams)
