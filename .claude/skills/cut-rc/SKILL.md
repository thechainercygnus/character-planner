---
name: cut-rc
description: Tag and publish a test release (vX.Y.Z-rc.N) of this repo when Bryce asks, then report the image digest and a test checklist built from what changed since the last tag. Use for "tag rc", "mint an RC build", "cut rc.N". Full releases follow docs/releasing.md instead.
---

# Cut a test release

Tagging is Bryce's call (CLAUDE.md): only tag when he asks, in his own words, in this
conversation. The steps are `docs/releasing.md`'s **Test releases**, plus checks that
caught mistakes before.

## 1. Check everything he expects is merged
```bash
gh pr view <n> --json state,mergeCommit --jq '.state + " " + .mergeCommit.oid[0:7]'
```
Do this for each PR he named, or that's meant to be in the build. If one is still `OPEN`,
don't tag. Tell him it's open and why it matters (#166 once needed a second click). Wait.

## 2. Pick the tag
```bash
git switch main && git pull
grep -m1 '^version' pyproject.toml        # X.Y.Z: rc tags don't bump it
git tag --list "vX.Y.Z-rc.*" --sort=-v:refname | head -1   # the last rc: N is one more
```
Tags carry the `v` prefix (`release.yml` runs on `v*`), even if Bryce writes `0.5.0-rc.4`.
A tag that failed is never reused: take the next N.

## 3. Tag the merge commit and push
```bash
git log --oneline -1          # must be the merge of the last PR he expects
git tag -a vX.Y.Z-rc.N -m "vX.Y.Z-rc.N: <what's new, a few words>" HEAD
git push origin vX.Y.Z-rc.N
```

## 4. Watch the release
```bash
gh run list --workflow release.yml --limit 5 --json databaseId,headBranch \
  --jq '.[] | select(.headBranch=="vX.Y.Z-rc.N") | .databaseId'   # retry for a few seconds
gh run watch <id> --exit-status --interval 30 >/dev/null 2>&1; gh run view <id> --json conclusion --jq .conclusion
docker buildx imagetools inspect ghcr.io/thechainercygnus/character-planner:X.Y.Z-rc.N | grep -m1 '^Digest'
```
If it fails, read the failed job's log (`gh run view <id> --log-failed`). Fix it on a
branch through `ship-pr`, and tag the next rc once that's merged.

## 5. Report, with a test checklist
Give Bryce:
- **The image:** `ghcr.io/thechainercygnus/character-planner:X.Y.Z-rc.N@sha256:<digest>`,
  for `PLANNER_IMAGE` in `.env`.
- **How to deploy it:** the compose command for his stack. The homelab runs `compose.yaml`
  with `compose.postgres.yaml`, `compose.redis.yaml` and `compose.tailscale.yaml`.
- **What to test:** one numbered list per change since the previous tag:
  ```bash
  git log --merges --oneline <previous tag>..vX.Y.Z-rc.N
  ```
  For each merged PR, write steps he can follow in the app, and what he should see. Skip
  PRs with nothing to see (docs, CI). Mark anything that needs a second account or
  Discord setup.

## 6. Offer the Portainer pin
`deploy/portainer.yaml` pins its default image by tag and digest. Offer a small PR (via
`ship-pr`) moving it to the new rc. Don't open it unasked.

The Portainer redeploy webhook lives in Claude's memory, not the repo. Trigger it only
when Bryce asks, and never write it anywhere.
