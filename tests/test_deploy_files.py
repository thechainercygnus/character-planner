"""The deployment files people paste or run as they are: every image pinned by digest, and
the Portainer stack self-contained (#61, CLAUDE.md's pinning rule)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from .conftest import REPO_ROOT

PINNED = {
    "deploy/portainer.yaml": REPO_ROOT / "deploy" / "portainer.yaml",
    "compose.postgres.yaml": REPO_ROOT / "compose.postgres.yaml",
}
# The planner's image is a default inside an override variable; the check reads the default.
OVERRIDABLE = "${PLANNER_IMAGE:-"


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def images(stack: Any) -> list[str]:
    return [str(service["image"]) for service in stack["services"].values() if "image" in service]


@pytest.mark.parametrize("name", sorted(PINNED))
def test_every_image_is_pinned_by_tag_and_digest(name: str) -> None:
    for image in images(load(PINNED[name])):
        default = image[len(OVERRIDABLE) : -1] if image.startswith(OVERRIDABLE) else image
        repository, _, digest = default.partition("@")
        assert ":" in repository and digest.startswith("sha256:"), f"{name}: {image}"


def test_the_portainer_stack_needs_nothing_from_the_repository() -> None:
    stack = load(PINNED["deploy/portainer.yaml"])
    assert set(stack["services"]) == {"tailscale", "migrate", "app", "worker"}
    for name, service in stack["services"].items():
        assert "build" not in service and "env_file" not in service, name
        for volume in service.get("volumes", []):
            assert not str(volume).startswith((".", "/")), f"{name} mounts {volume}"
    # Tailscale fills ${TS_CERT_DOMAIN} in the serve config; Compose must leave it alone.
    command = stack["services"]["tailscale"]["command"][0]
    assert "$${TS_CERT_DOMAIN}:443" in command
    # Nothing on the host's ports: the app is reached over the tailnet only.
    assert all("ports" not in service for service in stack["services"].values())
    assert stack["services"]["app"]["network_mode"] == "service:tailscale"
