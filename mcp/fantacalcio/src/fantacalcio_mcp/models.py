"""Pydantic views over the API's abbreviated payloads.

Naming rule: a field is renamed only where observed data confirms its meaning.
Everything else survives untouched in `raw`, because a misnamed field is worse
than an absent one -- the caller cannot tell it is wrong.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field

# Confirmed bonus/malus keys from settings/calculate.
BONUS_MALUS_NAMES = {
    "bmgs": "goal_scored",
    "bmgc": "goal_conceded",
    "bmpsc": "penalty_scored",
    "bmpns": "penalty_missed",
    "bmpsa": "penalty_saved",
    "bmyc": "yellow_card",
    "bmrc": "red_card",
    "bmog": "own_goal",
    # bmasf/bmass/bmasg all carry identical values in every fixture seen --
    # the data cannot distinguish "first"/"second"/"generic" assist, so they
    # stay unrenamed and reachable only via raw["calculate"]["bnMls"].
    "motm": "man_of_the_match",
}


class Coach(BaseModel):
    coach_id: int
    name: str


class Team(BaseModel):
    team_id: int
    name: str
    owner_username: str | None = None
    owner_user_id: int | None = None
    division: str | None = None
    credits_initial: int | None = None
    credits_spent: int | None = None
    credits_remaining: int | None = None
    roster_counts: dict[str, int] = Field(default_factory=dict)
    coaches: list[Coach] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(
            team_id=payload["id"],
            name=payload.get("n", ""),
            owner_username=payload.get("nu"),
            owner_user_id=payload.get("idu"),
            division=payload.get("d"),
            credits_initial=payload.get("cri"),
            credits_spent=payload.get("crs"),
            credits_remaining=payload.get("cr"),
            roster_counts=payload.get("r") or {},
            coaches=[Coach(coach_id=c["id"], name=c.get("n", ""))
                     for c in payload.get("all") or []],
            raw=payload,
        )


class Admin(BaseModel):
    admin_id: int
    name: str


class League(BaseModel):
    league_id: int
    name: str
    alias: str | None = None
    founded: str | None = None
    president: str | None = None
    team_count: int | None = None
    admins: list[Admin] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        lega = dict(payload.get("lega") or payload)
        lega.pop("parola", None)          # never surface the join password (real secret)
        # NOTE: parola_ordine is a boolean "league is password protected" flag,
        # not the secret itself -- it is NOT popped and stays in raw.
        return cls(
            league_id=lega["id"],
            name=lega.get("nome", ""),
            alias=lega.get("alias"),
            founded=lega.get("anno_fondazione"),
            president=lega.get("presidente"),
            team_count=lega.get("n_s"),
            admins=[Admin(admin_id=a["id"], name=a.get("nome", ""))
                    for a in lega.get("admins") or []],
            raw=lega,
        )


class LeagueStatus(BaseModel):
    season_id: int | None = None
    matchday: int | None = None
    matchday_start: str | None = None
    active: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(
            season_id=payload.get("sId"),
            matchday=payload.get("mday"),
            matchday_start=payload.get("mstr"),
            active=payload.get("activ"),
            raw=payload,
        )


class LeagueSettings(BaseModel):
    budget: int | None = None
    roster_min: int | None = None
    roster_max: int | None = None
    bench_size: int | None = None
    modules: list[str] = Field(default_factory=list)
    substitutions: int | None = None
    bonus_malus: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, rosters: dict[str, Any], lineup: dict[str, Any],
                 calculate: dict[str, Any]) -> Self:
        bn = calculate.get("bnMls") or {}
        return cls(
            budget=rosters.get("budg"),
            roster_min=rosters.get("msltc"),
            roster_max=rosters.get("xsltc"),
            bench_size=lineup.get("tbench"),
            modules=list(lineup.get("mods") or []),
            substitutions=(calculate.get("subst") or {}).get("ssnum"),
            bonus_malus={friendly: bn[key]
                         for key, friendly in BONUS_MALUS_NAMES.items() if key in bn},
            raw={"rosters": rosters, "lineup": lineup, "calculate": calculate},
        )


class Participant(BaseModel):
    """A team entry from the participants list.

    Deliberate exception to raw fidelity: `raw["coaches"][*]["email"]` is
    stripped. Every other model's `raw` preserves the payload verbatim, but
    the spec requires that manager email addresses never be forwarded, and
    that requirement outranks raw fidelity here.
    """

    team_id: int
    team_name: str
    managers: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        scrubbed = dict(payload)
        scrubbed["coaches"] = [{k: v for k, v in c.items() if k != "email"}
                               for c in payload.get("coaches") or []]
        return cls(
            team_id=payload["teamId"],
            team_name=payload.get("teamName", ""),
            managers=[c.get("name", "") for c in payload.get("coaches") or []],
            raw=scrubbed,
        )


class ServerTime(BaseModel):
    seconds: str | None = None
    minutes: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        return cls(seconds=payload.get("secs"), minutes=payload.get("mins"), raw=payload)


class AccountLeague(BaseModel):
    league_id: int
    name: str
    alias: str
    team_id: int | None = None


class Account(BaseModel):
    user_id: int
    username: str
    leagues: list[AccountLeague] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Self:
        data = payload.get("data", payload)
        utente = data.get("utente") or {}
        return cls(
            user_id=utente.get("id"),
            username=utente.get("username", ""),
            leagues=[
                AccountLeague(
                    league_id=lg["id"], name=lg.get("nome", ""),
                    alias=lg.get("alias", ""), team_id=lg.get("id_squadra"),
                )
                for lg in data.get("leghe") or []
            ],
        )
