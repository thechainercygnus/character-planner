"""The pre-commit hooks (#57): the push hook runs the Semgrep CI runs."""

import re
from typing import Any

import yaml

from .conftest import REPO_ROOT


def hooks() -> dict[str, dict[str, Any]]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def test_the_push_hooks_run_the_semgrep_ci_runs() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "semgrep.yml").read_text(encoding="utf-8")
    pinned = re.search(r"SEMGREP: (semgrep==[\d.]+)", workflow)
    assert pinned, "semgrep.yml pins SEMGREP"
    for name in ("semgrep-rules", "semgrep-rule-tests"):
        hook = hooks()[name]
        assert f"--from {pinned[1]} " in hook["entry"], f"{name}: bump it with semgrep.yml"
        assert hook["stages"] == ["pre-push"]


def test_the_other_hooks_stay_at_commit() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    assert config["default_stages"] == ["pre-commit"]
    assert set(config["default_install_hook_types"]) == {"pre-commit", "pre-push"}
