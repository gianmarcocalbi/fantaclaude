"""FastMCP tool surface. No HTTP here -- only api calls and model decoding.

Every tool is read-only and delegates all network I/O, auth, retries and
401-recovery to `api` (a `FantacalcioAPI`, or anything shaped like one --
see the tests, which pass a fixture-backed fake). This module never touches
httpx directly and never retries a call itself: `FantacalcioAPI._get`
already recovers from a stale token exactly once per call, and duplicating
that here would just double the recovery attempts `Auth`'s login cooldown
is built to bound.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .models import (
    Account, League, LeagueSettings, LeagueStatus, Participant, ServerTime, Team,
)

INSTRUCTIONS = (
    "Read-only access to a Leghe Fantacalcio.it league. League context comes "
    "from the configured account; pass `league` (the alias) only when the "
    "account belongs to more than one league."
)


def _is_email_key(key: Any) -> bool:
    """True for any key that carries an email address, however spelled.

    Normalised (case-folded, separators dropped) so `email`, `e_mail`,
    `E-Mail`, `emailAddress` and `userEmail` all match. Erring towards
    dropping one field too many is the right trade here: these payloads
    are invitation metadata, and a lost `emailVerified` flag costs nothing
    next to forwarding somebody's address.
    """
    if not isinstance(key, str):
        return False
    normalised = "".join(ch for ch in key.lower() if ch.isalnum())
    return "email" in normalised or normalised in {"mail", "mails"}


def _without_emails(value: Any) -> Any:
    """Drop every email-bearing key at ANY depth, preserving all else.

    The previous hand-rolled strip only removed an `email` key at the top
    level of each invitee row. `invitees.json` is `[]` -- the shape was
    never observed -- so that was a guess, and against the shape its
    sibling endpoint `/invitation/participants` actually returns
    (`{teamId, teamName, coaches: [{id, name, email, ...}]}`) it stripped
    nothing at all and forwarded every address. Recursing by key holds for
    whatever the endpoint really returns, which matters precisely because
    the real shape is still unobserved.
    """
    if isinstance(value, dict):
        return {k: _without_emails(v) for k, v in value.items() if not _is_email_key(k)}
    if isinstance(value, list):
        return [_without_emails(item) for item in value]
    return value


def build_server(api: Any) -> FastMCP:
    """Build the FastMCP server exposing exactly seven read-only tools over `api`.

    `api` only needs to satisfy the shape of `FantacalcioAPI` (see
    `tests/test_server.py`'s `FakeAPI` for the exact surface used); this
    function performs no HTTP itself.
    """
    mcp = FastMCP(name="fantacalcio", instructions=INSTRUCTIONS)

    @mcp.tool
    async def get_account() -> dict[str, Any]:
        """Read the signed-in Fantacalcio account and every league it belongs to.

        Returns the account's numeric user id, username, and the list of
        leagues it participates in (each with the league's id, name, alias
        and the account's team id in that league). Use this first when you
        need a league `alias` to pass to the other tools. Never returns
        authentication tokens or the account's email address.
        """
        account = Account.from_api(await api.profile())
        return account.model_dump()

    @mcp.tool
    async def get_league(league: str | None = None) -> dict[str, Any]:
        """Read one league's identity and current state.

        Combines the league's static profile (name, id, alias, founding
        year, president, admin list, team count) with its live status
        (season id, current matchday, matchday kickoff time, whether the
        season is active). Pass `league` (the alias) only if the signed-in
        account belongs to more than one league; otherwise the account's
        single league is used. Never returns the league's join password.
        """
        profile = League.from_api(await api.league_profile(league=league))
        status = LeagueStatus.from_api(await api.league_status(league=league))
        payload = profile.model_dump()
        payload["status"] = status.model_dump()
        return payload

    @mcp.tool
    async def get_league_settings(league: str | None = None) -> dict[str, Any]:
        """Read the league's scoring and roster rules.

        Merges the league's roster settings (budget, minimum/maximum roster
        size), lineup settings (bench size, allowed formations) and
        calculation settings (substitutions allowed per matchday, and the
        bonus/malus point table for goals, cards, penalties, etc.) into one
        result. Fields whose exact meaning has not been confirmed from
        observed data are preserved untouched under `raw` rather than
        guessed at.
        """
        settings = LeagueSettings.from_api(
            rosters=await api.roster_settings(league=league),
            lineup=await api.lineup_settings(league=league),
            calculate=await api.calculation_settings(league=league),
        )
        return settings.model_dump()

    @mcp.tool
    async def get_my_team(league: str | None = None) -> dict[str, Any]:
        """Read the signed-in user's own team in the league.

        Returns the team's name, division, credits spent/remaining/initial,
        roster composition counts by role, and its co-managers. Pass
        `league` (the alias) only if the account belongs to more than one
        league.
        """
        return Team.from_api(await api.my_team(league=league)).model_dump()

    @mcp.tool
    async def list_teams(include_pending: bool = False,
                         league: str | None = None) -> dict[str, Any]:
        """List every team in the league, with its managers, credits and division.

        Each team includes its name, division, credit totals and the names
        of its managers (never their email addresses -- those are stripped
        before this tool returns anything). Set `include_pending` to also
        list outstanding invitations that have not yet been accepted (also
        with any email address stripped). Pass `league` (the alias) only if
        the account belongs to more than one league.
        """
        envelope = await api.teams(page=1, league=league)
        rows = envelope.get("data") if isinstance(envelope, dict) else envelope
        teams = [Team.from_api(row) for row in rows or []]

        roster = await api.participants(league=league)
        managers = {p.team_id: p.managers
                    for p in (Participant.from_api(r) for r in roster or [])}

        payload: dict[str, Any] = {
            "teams": [{**team.model_dump(), "managers": managers.get(team.team_id, [])}
                      for team in teams],
            "divisions": envelope.get("divisions") if isinstance(envelope, dict) else None,
        }
        if include_pending:
            # Recursive, key-based scrub -- see _without_emails. Also keeps
            # a paginated envelope intact instead of iterating its keys,
            # which the old row-wise comprehension would have done.
            payload["pending_invites"] = _without_emails(
                await api.invitees(league=league) or [])
        return payload

    @mcp.tool
    async def list_competitions(league: str | None = None) -> dict[str, Any]:
        """List the competitions configured in the league (campionato, coppa, ...).

        An empty list means the league has not created any competition yet.
        Pass `league` (the alias) only if the account belongs to more than
        one league.
        """
        return {"competitions": await api.competitions(league=league) or []}

    @mcp.tool
    async def get_server_time(league: str | None = None) -> dict[str, Any]:
        """Read Fantacalcio's own server clock, for reasoning about deadlines.

        Returns the server's current time as `YYYYMMDDHHMMSS` (seconds
        precision) and `YYYYMMDDHHMM` (minutes precision) strings, which is
        the API's native format -- useful for comparing against a
        matchday's kickoff time from `get_league`.
        """
        return ServerTime.from_api(await api.server_time(league=league)).model_dump()

    return mcp
