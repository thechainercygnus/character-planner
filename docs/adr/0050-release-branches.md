# 0050: Release branches: development on main, one release branch for patches

Status: accepted (2026-11-18)

## Context

v0.5.1 and v0.5.2 needed fixes while `main` already held unfinished v0.6.0 work: the game
data parser and upload route, with a migration. Tagging `main` would have shipped them.
So `release/0.5` was made from the `v0.5.0` tag, and the fixes were backported to it. This
records that as the standing way to release.

## Decision

Bryce chose this on 2026-11-18, over moving development off `main` (GitFlow).

1. **Development stays on `main`.** Features and fixes go there first, and minor and major
   releases (`vX.Y.0`) are tagged there. Dependabot, CI, the roadmap, the skills and the
   docs site's "latest" all follow `main`.
2. **Each minor or major release starts `release/X.Y`** from its tag, at release time,
   not when the first patch is needed.
3. **Only the newest release gets patches.** When `release/X.Y` starts, the previous
   release branch retires and can be deleted. Its tags keep everything it released.
4. **Patches are backports.** A fix lands on `main`, is cherry-picked (`-x`) to
   `release/X.Y` by pull request, and is tagged there. The release branch then merges back
   into `main`, as a merge commit.
5. **`release/**` is protected like `main`,** and gets the same security workflows (#199).

## Consequences

- **At most two branches take changes:** `main`, and the current `release/X.Y`. A pull
  request's base follows from its milestone.
- **Patch PRs aren't auto-closing.** GitHub only closes issues from the default branch, so
  issues close with the merge-back.
- **Releasing a minor version adds one step:** start its release branch, and retire the
  previous one (`docs/releasing.md`, "Cutting a release", step 6).
- **`release/0.5`** retires when v0.6.0 is released. Until then it can still take patches
  such as #212 and #213.
