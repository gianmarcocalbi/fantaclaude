"""The two news lists: squalificati/diffidati and infortunati (spec, "The
news adapter, and what fantacalcio.it already publishes").

Captured 2026-09-05, one anonymous request each (`captured/
squalificati-2026-09-05.html`, `captured/infortunati-2026-09-05.html`; the
fixtures are the Atalanta and Bologna cards trimmed from them by
`_extract_news.py`). Both pages are twenty club cards, `div.card.team-card`,
each opened by `span.team-name` -- the club as the listone spells it -- and
holding plain entries: `strong.item-name` (the player written the listone's
way, "Sulemana K.") followed by `div.item-description` (the page's prose).
There is NO link and NO player id anywhere on either page, so the join is
the repo's name-matching rule, not the free one the probabili page gives:
the club through `resolve_team` and the `fantacalcio` team aliases, the
player through `match_listone` against that club's candidates alone, and a
name that resolves to nobody is written with a null player_id and counted,
never dropped and never matched across clubs.

The suspensions page has two columns per club, each headed by a
`strong.label` reading "Squalificati" or "Diffidati", and a column with
nobody in it is `div.empty-list-message`. On the capture every column was
empty -- giornata 3 in progress, no Giudice Sportivo ruling yet, nobody on
four yellows after two rounds -- so the shape of a suspension entry is
INFERRED to be the injuries page's, not observed; Task 12's Tuesday capture
confirms or corrects it. The injuries page has one unlabelled list per club,
whose kind is the page's. The team menu above the cards and the matchweek
widget elsewhere repeat every club as `team-name team-link` anchors: neither
is a card, and a club name is read only inside a card.

The constants below pin what the captures showed; a page that no longer
matches fails loud (`NewsShapeError`), never silently.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import duckdb
import httpx

from fantaclaude.ingest.http import fetch_bytes
from fantaclaude.ingest.names import (
    UNMATCHED,
    Candidate,
    Match,
    load_aliases,
    load_candidates,
    load_teams,
    match_listone,
    resolve_team,
)
from fantaclaude.ingest.raw import RawFile, RawStore
from fantaclaude.timeutil import to_db

ORIGIN = "https://www.fantacalcio.it"
URLS = {"squalificati": f"{ORIGIN}/squalificati-e-diffidati-campionato-serie-a",
        "infortunati": f"{ORIGIN}/infortunati-serie-a"}
PAGES = tuple(URLS)
ALIAS_SOURCE = "fantacalcio"                   # the team aliases the calendar already keeps for this host
KINDS = ("squalificato", "diffidato", "infortunato")

# Pinned against the 2026-09-05 captures and verified against the fixtures.
CARD_CLASS = "team-card"
TEAM_NAME_CLASS = "team-name"
LABEL_CLASS = "label"
ITEM_NAME_CLASS = "item-name"
ITEM_DESCRIPTION_CLASS = "item-description"
EMPTY_CLASS = "empty-list-message"
LABEL_KINDS = (("squalific", "squalificato"), ("diffid", "diffidato"))
PAGE_KIND = {"infortunati": "infortunato"}     # a page whose lists carry no label
VOID_TAGS = frozenset({"meta", "img", "br", "input", "link", "hr", "source"})


def source_of(page: str) -> str:
    return f"fantacalcio.it:{URLS[page].removeprefix(ORIGIN)}"


class NewsShapeError(ValueError):
    """The page is not the list this adapter was written against."""


@dataclass(frozen=True)
class NewsRow:
    kind: str
    team_name: str
    name: str
    detail: str
    position: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class NewsPage:
    page: str
    rows: list[NewsRow]
    teams: int
    empty_lists: int


class _Parser(HTMLParser):
    """A flat event stream in document order: card, team, label, name,
    detail, empty. Grouping into rows happens afterwards, on the stream."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self._stack: list[tuple[str, str | None, bool]] = []     # (tag, capture kind, opens a card)
        self._buffers: list[list[str]] = []

    @property
    def _in_card(self) -> bool:
        return any(is_card for _, _, is_card in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, dict(attrs), void=True)

    def _open(self, tag: str, a: dict[str, str | None], *, void: bool) -> None:
        classes = str(a.get("class") or "").split()
        is_card = CARD_CLASS in classes
        if is_card:
            self.events.append(("card", ""))
        capture = None
        if is_card or self._in_card:
            if TEAM_NAME_CLASS in classes and tag == "span":
                capture = "team"
            elif LABEL_CLASS in classes and tag == "strong":
                capture = "label"
            elif ITEM_NAME_CLASS in classes:
                capture = "name"
            elif ITEM_DESCRIPTION_CLASS in classes:
                capture = "detail"
            elif EMPTY_CLASS in classes:
                self.events.append(("empty", ""))
        if void:
            return
        self._stack.append((tag, capture, is_card))
        if capture:
            self._buffers.append([])

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, *_ in self._stack):
            return          # a stray end tag closes nothing; draining past it would forget every open tag
        while self._stack:
            open_tag, capture, _ = self._stack.pop()
            if capture:
                self.events.append((capture, " ".join("".join(self._buffers.pop()).split())))
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._buffers:
            self._buffers[-1].append(data)


def _kind_of(label: str) -> str:
    lowered = label.lower()
    for prefix, kind in LABEL_KINDS:
        if lowered.startswith(prefix):
            return kind
    raise NewsShapeError(f"unknown list label {label!r} -- the page names a list this adapter does not know")


def parse_news_page(html_text: str, *, page: str) -> NewsPage:
    if page not in PAGES:
        raise ValueError(f"page must be one of {PAGES}, got {page!r}")
    parser = _Parser()
    parser.feed(html_text)
    if not any(kind == "card" for kind, _ in parser.events):
        raise NewsShapeError(f"no div.{CARD_CLASS} on the page -- the {page} layout changed")
    default_kind = PAGE_KIND.get(page)
    rows: list[NewsRow] = []
    teams = empty = 0
    team: str | None = None
    label: str | None = None
    kind = default_kind
    pending: str | None = None

    def flush(detail: str = "") -> None:
        nonlocal pending
        if pending is not None:
            rows.append(NewsRow(str(kind), str(team), pending, detail, len(rows), {"team": team, "label": label}))
            pending = None

    for event, text in parser.events:
        if event == "card":
            flush()
            team, label, kind = None, None, default_kind
        elif event == "team":
            team = text
            teams += 1
        elif event == "label":
            flush()
            label, kind = text, _kind_of(text)
        elif event == "name":
            flush()
            if team is None:
                raise NewsShapeError(f"{text!r} is listed before any club name -- the card layout changed")
            if kind is None:
                raise NewsShapeError(f"{text!r} is listed under no label on the {page} page")
            pending = text
        elif event == "detail":
            if pending is None:
                raise NewsShapeError(f"an item description with no name before it ({text[:40]!r})")
            flush(text)
        elif event == "empty":
            empty += 1
    flush()
    if page not in PAGE_KIND and not any(event == "label" for event, _ in parser.events):
        raise NewsShapeError(f"no strong.{LABEL_CLASS} on the page -- the {page} columns are no longer labelled")
    return NewsPage(page, rows, teams, empty)


async def fetch_news(http: httpx.AsyncClient, store: RawStore, *, page: str, label: str) -> RawFile:
    data = await fetch_bytes(http, URLS[page])
    return store.write_bytes("news", data, ext="html", label=f"{page}-{label}")


@dataclass(frozen=True)
class NewsIngestResult:
    page: str
    file_id: int
    season_id: int
    giornata: int
    inserted: int
    skipped_duplicate: bool
    teams: int
    empty_lists: int
    unmatched: int
    unknown_teams: int
    sha256: str
    raw_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "file_id": self.file_id, "season_id": self.season_id, "giornata": self.giornata,
                "inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate, "teams": self.teams,
                "empty_lists": self.empty_lists, "unmatched": self.unmatched, "unknown_teams": self.unknown_teams,
                "sha256": self.sha256, "raw_path": self.raw_path}


def match_rows(page: NewsPage, *, teams: dict[str, str], team_aliases: dict[str, str],
               candidates: list[Candidate]) -> list[tuple[NewsRow, str | None, Match]]:
    """Every row with the club it resolves to and the listone match within
    that club -- a candidate of another club is never considered."""
    by_team: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_team[c.team_short].append(c)
    out = []
    for row in page.rows:
        short = resolve_team(row.team_name, teams, team_aliases)
        match = match_listone(row.name, by_team.get(short, [])) if short else Match(None, UNMATCHED)
        out.append((row, short, match))
    return out


def record_news(con: duckdb.DuckDBPyConnection, season_id: int, giornata: int, page: NewsPage, raw: RawFile, *,
                aliases_path: Path) -> NewsIngestResult:
    """Append one file row and its entries; the same bytes for the same page
    and giornata is a no-op. A later fetch is a later file: v_news_files_current
    picks the newest per page, and nothing is overwritten."""
    existing = con.execute("SELECT file_id, unmatched FROM news_files WHERE kind = ? AND season_id = ? AND giornata = ? "
                           "AND sha256 = ?", [page.page, season_id, giornata, raw.sha256]).fetchone()
    if existing is not None:
        return NewsIngestResult(page.page, int(existing[0]), season_id, giornata, 0, True, page.teams, page.empty_lists,
                                int(existing[1]), 0, raw.sha256, str(raw.path))
    matched = match_rows(page, teams=load_teams(con), team_aliases=load_aliases(aliases_path).teams_for(ALIAS_SOURCE),
                         candidates=load_candidates(con))
    unmatched = sum(1 for _, _, m in matched if m.player_id is None)
    unknown_teams = len({row.team_name for row, short, _ in matched if short is None})
    con.begin()
    try:
        file_id = con.execute(
            "INSERT INTO news_files (kind, season_id, giornata, fetched_at, source, raw_path, sha256, row_count, teams, "
            "unmatched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING file_id",
            [page.page, season_id, giornata, to_db(raw.fetched_at), source_of(page.page), str(raw.path), raw.sha256,
             len(page.rows), page.teams, unmatched]).fetchone()[0]
        if matched:                        # a page whose every column is empty (a capture before any ruling) has none
            con.executemany(
                "INSERT INTO unavailable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)",
                [[file_id, season_id, giornata, row.kind, row.team_name, short, row.name, match.player_id, match.status,
                  row.detail or None, row.position, json.dumps({**row.raw, "candidates": list(match.candidates)}, ensure_ascii=False)]
                 for row, short, match in matched])
    except Exception:
        con.rollback()
        raise
    con.commit()
    return NewsIngestResult(page.page, int(file_id), season_id, giornata, len(page.rows), False, page.teams,
                            page.empty_lists, unmatched, unknown_teams, raw.sha256, str(raw.path))
