# Releasing

Releases are tags. Pushing a tag `vX.Y.Z` that matches `pyproject.toml`'s version runs
`.github/workflows/release.yml` (#61, ADR 0026). The workflow:

1. checks that the tag and the version match;
2. builds the image for amd64 and scans it with Trivy. A fixable high or critical
   vulnerability stops the release before anything is published;
3. builds and pushes `ghcr.io/thechainercygnus/character-planner` for amd64 and arm64, tagged
   `X.Y.Z`, `X.Y` and `latest`;
4. attests build provenance, signs the image with cosign (keyless), and makes a CycloneDX
   SBOM;
5. creates the GitHub release:
   - the notes start with a **Security** section, then the image and GitHub's list of merged
     PRs;
   - the SBOM is attached.

## Cutting a release

1. **Bump the version** in `pyproject.toml` on a branch, run `uv lock`, and merge the PR.
   Versions are `0.x` until the app is ready for others: a minor bump for features, a patch
   for fixes.
2. **Label vulnerability fixes.** Every PR merged since the last tag that fixed a
   vulnerability should carry the `security` label, with the advisory or CVE in its title.
   They make the Security section; with none, it says so.
3. **Tag the merge commit on `main`** and push the tag:

   ```bash
   git switch main && git pull
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

4. **Watch the run** (`gh run watch`), then read the release. If the scan fails, fix the
   image (usually a base image or dependency update), merge, and tag the next patch version.
   A tag that failed isn't reused.
5. **Pin the Portainer stack to it.** In a small PR, set `deploy/portainer.yaml`'s default
   image to the new release, by tag and digest:

   ```bash
   docker buildx imagetools inspect ghcr.io/thechainercygnus/character-planner:X.Y.Z
   ```

   The digest exists only once the image is published, so this comes after the release.
   Test releases (rc) can be pinned the same way while they're being tried.

### Test releases

To try a release before making it, tag `vX.Y.Z-rc.N` for the version in `pyproject.toml` (no
bump needed), for example `v0.1.0-rc.1`:
- It runs the same workflow and publishes only `X.Y.Z-rc.N`: not `X.Y` or `latest`.
- Its GitHub release is marked as a pre-release.
- The final release's notes count from the previous full release, skipping the rc tags.

The first publish creates the package on GitHub as **private**. Make it public once, in
the package's settings (Package settings, Danger zone, Change visibility), so others can
pull it without logging in.

## Reproducible builds

What's in an image, and whether building the same commit again gives the same bytes:

- **The web app** is built by Vite from `package-lock.json`. Two clean builds of the same
  commit give a bit-for-bit identical bundle, and CI checks that on every push
  (`frontend` job, "Reproducible build").
- **The Python code** isn't compiled. The image runs the source as committed, with
  dependencies installed from `uv.lock` (exact versions and hashes, `uv sync --locked`).
- **Base images** are pinned by digest, and the GitHub Actions that build them by commit.
- **The image as a whole** isn't bit-for-bit reproducible: layers carry build timestamps
  and file metadata. Its contents are fixed by the points above, and each released image
  carries signed build provenance that ties it to the commit and the workflow run that
  built it (below).

## Verifying an image

Both checks need the image's digest, from the release notes or
`docker buildx imagetools inspect`.

```bash
# Build provenance: built by this repository's release workflow
gh attestation verify oci://ghcr.io/thechainercygnus/character-planner:0.2.0 \
  --repo thechainercygnus/character-planner

# Signature: signed keylessly by the release workflow, on a tag
cosign verify ghcr.io/thechainercygnus/character-planner:0.2.0 \
  --certificate-identity-regexp '^https://github.com/thechainercygnus/character-planner/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The SBOM attached to each release lists every package in the image.
