#!/usr/bin/env bash
# Release notes for a tag (#61, ADR 0026), printed to stdout:
# - Security: every PR merged since the previous tag that carries the "security" label,
#   or "None" (OpenSSF release_notes_vulns, #86). Label a PR "security" when it fixes a
#   vulnerability, and name the advisory or CVE in its title.
# - The image, by tag and digest, and how to verify it.
# - GitHub's generated notes: merged PRs and contributors.
#
# Usage: release-notes.sh <tag> <image> <digest>   (needs GH_TOKEN and full git history)
set -euo pipefail

tag="$1"
image="$2"
digest="$3"
repo="${GITHUB_REPOSITORY:?}"

# The previous full release: test releases (vX.Y.Z-rc.N) are skipped, so the final
# release lists everything since the last one, not only what came after its rc.
previous="$(git describe --tags --abbrev=0 --match 'v*' --exclude 'v*-*' "${tag}^" 2>/dev/null || true)"
range="${previous:+${previous}..}${tag}"

# PRs merged in this release, from the merge commits ("Merge pull request #91 from ...").
security=""
for pr in $(git log --format=%s "${range}" | sed -nE 's/^Merge pull request #([0-9]+) .*/\1/p'); do
  # Merges carried over from the archived repo name PRs that don't exist here: skip them.
  if gh pr view "${pr}" --repo "${repo}" --json labels --jq '.labels[].name' 2>/dev/null |
    grep -qx security; then
    title="$(gh pr view "${pr}" --repo "${repo}" --json title --jq .title)"
    security+="- ${title} (#${pr})"$'\n'
  fi
done

version="${tag#v}"
echo "## Security"
echo
if [ -n "${security}" ]; then
  printf '%s' "${security}"
else
  echo "None: no vulnerability fixes in this release."
fi
echo
echo "## Image"
echo
echo '```'
echo "docker pull ${image}:${version}"
echo "# ${image}@${digest}"
echo '```'
echo
echo "Linux amd64 and arm64. Signed with cosign (keyless) and attested with build provenance;"
echo "the CycloneDX SBOM is attached. To verify, see docs/releasing.md."
echo
args=(-f "tag_name=${tag}")
if [ -n "${previous}" ]; then
  args+=(-f "previous_tag_name=${previous}")
fi
gh api "repos/${repo}/releases/generate-notes" "${args[@]}" --jq .body
