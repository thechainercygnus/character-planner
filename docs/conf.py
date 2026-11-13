"""Sphinx configuration for the docs site on Read the Docs (#104).

The pages are the Markdown in docs/, read by MyST-Parser as they are. Build locally with:

    uv run --group docs sphinx-build -W -b html docs docs/_build/html
"""

# Imported as a module: Sphinx reads every top-level name here as a setting, and
# `version` is one.
import importlib.metadata

project = "Character Planner"
author = "Bryce Jenkins and contributors"
copyright = "2026, Bryce Jenkins and contributors. AGPL-3.0-or-later"
try:
    release = importlib.metadata.version("character-planner")
except importlib.metadata.PackageNotFoundError:  # Read the Docs installs only the docs group
    release = ""

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "vendor", "Thumbs.db", ".DS_Store"]

# Anchors for headings, so links like releasing.md#verifying-an-image resolve.
myst_heading_anchors = 3
# ```bash fences and pipe tables are already standard Markdown; these add ::: fences.
myst_enable_extensions = ["colon_fence"]

html_theme = "furo"
html_title = "Character Planner"
html_theme_options = {
    "source_repository": "https://github.com/thechainercygnus/character-planner/",
    "source_branch": "main",
    "source_directory": "docs/",
}
