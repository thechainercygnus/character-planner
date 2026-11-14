"""Settings loaded from the environment and .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Region = Literal["us", "eu", "kr", "tw"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bnet_client_id: str = ""
    bnet_client_secret: SecretStr = SecretStr("")
    bnet_region: Region = "us"
    bnet_redirect_uri: str = "http://localhost:8000/auth/callback"

    character_name: str = "Brumboldt"
    character_surname: str = "Doomlet"

    database_url: str = "sqlite:///data/character-planner.db"
    curated_dir: Path = Path("data/curated")

    # Where the browser lands after login. "/" when the backend serves the built
    # frontend; the Vite dev server's URL (http://localhost:5173/) during development.
    post_login_redirect: str = "/"
    frontend_dist: Path = Path("frontend/dist")

    # Seconds between Forever Companion requests in long batches (the item pool), to stay
    # under its 120 requests/min limit. Tests set 0.
    companion_request_pause: float = 0.55

    # The worker's schedule (worker.py, ADR 0011). Syncs use the app's own token (#107).
    sync_every_hours: float = 6
    pool_every_hours: float = 24
    # Enchant recipes are static: weekly is plenty (#87).
    enchants_every_hours: float = 168
    worker_poll_seconds: float = 60

    # Logging (ADR 0019). DEBUG adds every upstream request. With log_dir set, the API
    # writes server.log and access.log there and the worker writes worker.log.
    log_level: LogLevel = "INFO"
    log_format: Literal["text", "json"] = "text"
    log_dir: Path | None = None

    # The page footer's Source link (#43). The AGPL asks a hosted, modified copy to offer
    # its users its source: point this at your fork if you change the code.
    source_url: str = "https://github.com/thechainercygnus/character-planner"

    # Host names the API answers to (#124): a request for any other name gets 400, which
    # stops DNS rebinding. localhost, 127.0.0.1 and [::1] always work; add the names you
    # open it at, comma separated: a LAN address, your proxy's name. "*.ts.net" covers
    # Tailscale names (compose.tailscale.yaml sets it).
    planner_hosts: str = ""

    # Who runs this instance and how to reach them (#133): shown on the privacy notice,
    # so people know whom to ask about or to remove their data. An email address, a web
    # address or a name; empty shows a generic line.
    operator_contact: str = ""

    # Users (#16, ADR 0037). Off: no sign-in, as a single-person instance needs. On: every
    # /api request needs a Battle.net sign-in; the first one becomes the admin.
    planner_users: bool = False
    # With users on, whether new Battle.net accounts may sign up after the first.
    planner_signups: bool = False

    # Background jobs (#17, ADR 0039). Empty: a Sync runs in the web request. Set
    # (redis://...): it's queued and worked by `character-planner-jobs`.
    redis_url: str = ""
    # Minutes between syncs of one character by hand, to share the Battle.net budget
    # (#17). Counts from its last sync, scheduled ones included. 0 turns it off.
    sync_cooldown_minutes: float = 15
    # Minutes between manual starts of each bulk refresh (item pool, enchants, items,
    # talents), operator or not (#17). The worker's schedule isn't limited. 0 turns it off.
    refresh_cooldown_minutes: float = 10

    @property
    def trusted_hosts(self) -> list[str]:
        extra = [host.strip().lower() for host in self.planner_hosts.split(",") if host.strip()]
        return [*LOCAL_HOSTS, *extra]

    @field_validator("source_url")
    @classmethod
    def _web_address(cls, value: str) -> str:
        # Shown as a link: only a web address, never javascript: or the like.
        if not value.startswith(("https://", "http://")) or any(c.isspace() for c in value):
            raise ValueError("SOURCE_URL must be an http(s) address")
        return value

    @field_validator("operator_contact")
    @classmethod
    def _contact_text(cls, value: str) -> str:
        # One short line. The page links only an http(s) or email address; the rest is text.
        value = value.strip()
        if len(value) > 200 or any(not c.isprintable() for c in value):
            raise ValueError("OPERATOR_CONTACT must be one line of up to 200 characters")
        return value

    @property
    def api_base_url(self) -> str:
        return f"https://{self.bnet_region}.api.blizzard.com"

    @property
    def profile_namespace(self) -> str:
        # Undocumented; found by community probing after the 2026-11-04 launch.
        return f"profile-forever-{self.bnet_region}"

    @property
    def static_namespace(self) -> str:
        # Game data (item search, item media). The version-free name works; see ADR 0003.
        return f"static-forever-{self.bnet_region}"

    @property
    def character_slug(self) -> str:
        # Forever character routes use {name}-{surname}, lowercase.
        return f"{self.character_name}-{self.character_surname}".lower()

    @property
    def has_credentials(self) -> bool:
        return bool(self.bnet_client_id and self.bnet_client_secret.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
