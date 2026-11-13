# 0026: Tagged releases with images on GHCR

Status: accepted (2026-11-13). For self-hosting (ADR 0020), #61.

## Context

Self-hosters need an image to pull and a safe way to upgrade. Until now, every install built
from a checkout. The security track (#52, #86) asks for releases that are scanned, signed,
attested and have vulnerability notes.

## Decision

- **A tag is a release.**
  - `vX.Y.Z` must match `pyproject.toml`, the one version source; the startup log reports it.
  - `0.x` until the app is ready for others.
- **One workflow, `release.yml`, two jobs:**
  - `image` (`packages`, `id-token`, `attestations`): scan, push for amd64 and arm64, then
    attest, sign and make the SBOM.
  - `github-release` (`contents: write`): writes the notes and creates the release.
  - Third-party actions never run with `contents: write`.
- **Scan before publishing:**
  - Trivy scans an amd64 build first. Fixable high and critical vulnerabilities stop the
    release, so a known-vulnerable image is never pushed.
  - The arm64 build isn't scanned separately: same packages, different binaries. #54 adds
    scheduled scans and SARIF in CI.
- **Tags:** `X.Y.Z` (fixed), `X.Y` (follows patches), `latest`. No `v`, as Docker images
  usually have it.
- **Trust:**
  - build provenance with `actions/attest-build-provenance`, pushed to the registry;
  - a keyless cosign signature, with the workflow's identity;
  - a CycloneDX SBOM (Syft) attached to the release.
  - `docs/releasing.md` shows how to verify.
- **Security notes:** PRs merged since the previous tag with the `security` label are listed
  first in the notes, or "None" (#86, `release_notes_vulns`).
- **Compose:** `PLANNER_IMAGE` picks a published image; building from a checkout stays the
  default.
- **Frontend stage on the build platform:** static files are the same everywhere, so arm64
  builds don't run npm under emulation.

## Consequences

- The first push makes a private GHCR package. It's made public by hand, once.
- A failed release isn't re-tagged: fix it and tag the next patch.
- The `security` label is manual. A missed label means a missing note: check before tagging.
- Upgrading is pull and restart; migrations run in `migrate` (ADR 0022).
