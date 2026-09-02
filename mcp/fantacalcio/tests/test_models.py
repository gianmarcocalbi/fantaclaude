from fantacalcio_mcp.models import (
    Account,
    League,
    LeagueSettings,
    LeagueStatus,
    Participant,
    ServerTime,
    Team,
)


def test_team_decodes_confirmed_fields_only(fixture_json):
    team = Team.from_api(fixture_json("my_team"))
    assert team.name == "Sanzimippi FC"
    assert team.team_id == 11560832
    assert team.owner_username == "Edo"
    assert team.credits_initial == 500
    assert team.credits_spent == 0
    assert team.credits_remaining == 500
    assert team.division == "A"
    assert team.roster_counts == {"p": 0, "d": 0, "c": 0, "a": 0}
    assert [c.name for c in team.coaches] == ["Edo", "Himmy"]


def test_team_keeps_unknown_fields_in_raw(fixture_json):
    payload = fixture_json("my_team")
    team = Team.from_api(payload)
    # bm/st/pl are unconfirmed and must never be given a friendly name
    assert team.raw["bm"] == payload["bm"]
    assert team.raw["st"] == payload["st"]
    assert set(payload) <= set(team.raw), "raw must preserve every input key"


def test_league_omits_the_join_password(fixture_json):
    league = League.from_api(fixture_json("league_profile"))
    assert league.name == "Fantabalotelli3"
    assert league.league_id == 2578630
    assert league.founded == "2023"
    assert [a.name for a in league.admins] == ["KingNazzario", "Chuck"]
    assert "parola" not in league.raw


def test_league_strips_parola_but_keeps_parola_ordine(fixture_json):
    # No fixture carries a literal "parola" key (Task 2 scrubs it upstream),
    # so the fixture-only test above never actually exercises the stripping
    # logic. Inject one here to prove League.from_api really removes it, and
    # that the unrelated parola_ordine boolean flag is NOT removed with it.
    payload = fixture_json("league_profile")
    payload["lega"] = dict(payload["lega"])
    payload["lega"]["parola"] = "secret"
    league = League.from_api(payload)
    assert "parola" not in league.raw
    assert "secret" not in league.model_dump_json()
    assert league.raw["parola_ordine"] is True


def test_league_status_decodes(fixture_json):
    status = LeagueStatus.from_api(fixture_json("league_status"))
    assert status.season_id == 21
    assert status.matchday == 1
    assert status.matchday_start == "2026-08-22T16:30:00"
    assert status.active is True


def test_league_settings_merges_three_endpoints(fixture_json):
    settings = LeagueSettings.from_api(
        rosters=fixture_json("roster_settings"),
        lineup=fixture_json("lineup_settings"),
        calculate=fixture_json("calculation_settings"),
    )
    assert settings.budget == 500
    assert settings.roster_min == 23
    assert settings.roster_max == 40
    assert settings.bench_size == 12
    assert "442" in settings.modules
    assert settings.substitutions == 5
    assert settings.bonus_malus["goal_scored"] == [3, 3]
    assert settings.bonus_malus["yellow_card"] == [-0.5, -0.5]
    assert settings.bonus_malus["own_goal"] == [-1, -1]
    # unconfirmed knobs stay raw
    assert "lswi" in settings.raw["lineup"]
    assert "smodg" in settings.raw["calculate"]
    # bmasf/bmass/bmasg carry identical values in the fixture -- the data
    # cannot confirm "first"/"second"/"generic" assist, so they must not be
    # invented, but must still be reachable unrenamed via raw
    bn_raw = settings.raw["calculate"]["bnMls"]
    for unconfirmed_key, invented_name in (
        ("bmasf", "assist_first"), ("bmass", "assist_second"), ("bmasg", "assist_generic"),
    ):
        assert invented_name not in settings.bonus_malus
        assert bn_raw[unconfirmed_key] == [1, 1]


def test_server_time_decodes(fixture_json):
    assert ServerTime.from_api(fixture_json("server_time")).seconds == "20260822160844"


def test_account_lists_leagues_without_tokens(fixture_json):
    account = Account.from_api(fixture_json("profile"))
    assert account.username == "grimid3v"
    assert account.user_id == 10426252
    serialised = account.model_dump_json()
    assert "jwt" not in serialised and "eyJhbGci" not in serialised


def test_participant_decodes_confirmed_fields(fixture_json):
    payload = next(p for p in fixture_json("participants") if p["teamId"] == 11560832)
    participant = Participant.from_api(payload)
    assert participant.team_id == 11560832
    assert participant.team_name == "Sanzimippi FC"
    assert participant.managers == ["Edo", "Himmy"]


def test_participant_raw_preserves_non_email_coach_keys(fixture_json):
    payload = next(p for p in fixture_json("participants") if p["teamId"] == 11560832)
    participant = Participant.from_api(payload)
    for raw_coach, source_coach in zip(participant.raw["coaches"], payload["coaches"]):
        assert raw_coach["admin"] == source_coach["admin"]
        assert raw_coach["code"] == source_coach["code"]
        assert raw_coach["id"] == source_coach["id"]
        assert raw_coach["name"] == source_coach["name"]


def test_participant_never_leaks_email(fixture_json):
    for payload in fixture_json("participants"):
        participant = Participant.from_api(payload)
        assert all("email" not in coach for coach in participant.raw["coaches"])
        serialised = participant.model_dump_json()
        assert "email" not in serialised
        assert "<scrubbed>" not in serialised

