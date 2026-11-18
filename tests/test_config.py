from character_planner.config import Settings


def test_character_slug_is_lowercase_name_dash_surname(settings: Settings) -> None:
    assert settings.character_slug == "brumboldt-doomlet"


def test_region_drives_host_and_namespace(settings: Settings) -> None:
    eu = settings.model_copy(update={"bnet_region": "eu"})
    assert eu.api_base_url == "https://eu.api.blizzard.com"
    assert eu.profile_namespace == "profile-forever-eu"


def test_has_credentials_requires_both(settings: Settings) -> None:
    assert settings.has_credentials
    assert not settings.model_copy(update={"bnet_client_id": ""}).has_credentials


def test_the_planner_starts_blank_without_a_character_in_env() -> None:
    """#206: CHARACTER_NAME is optional; without it there's no character to seed."""
    blank = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (blank.character_name, blank.character_surname, blank.character_slug) == ("", "", "")
