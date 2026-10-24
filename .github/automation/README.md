# Upstream automation policy

- Daily and manual source sync follows `awesome-deepseekharness/awesome-deepseek-harness:main` into `sync-only/upstream-main`. It does not build or publish.
- Reviewed downstream policy paths are retained from a pinned default-branch commit. Only conflicts inside the explicit allowlist are resolved with that policy; all other source conflicts abort and list their paths. Pushes are normal, never forced.
- Existing historical tags and releases are never recreated or overwritten. Baseline deployment does not backfill releases.
- No recognized new upstream formal release means no automatic heavyweight build or publication. A source commit, website rebuild, tag alone, or dependency update is not a release signal.
- Manual build and promotion remain separate where the repository has a real deliverable. Repositories without a build/publisher do not gain a fabricated release route.
- Lightweight read-only safety checks remain enabled. This policy does not enable third-party dispatch, credentials, external AI, or repository security settings.
- Website repositories sync into a non-publishing source branch. Publication requires an explicit manual promotion of verified build artifacts; no automatic merge into the live Pages source.

## Manual website operations

Run `site.yml` on the default branch with the full source commit (including a reviewed source-sync commit). This builds only and retains `site-candidate` for 30 days. Record the run ID, source SHA and artifact.tar SHA256 from the summary. The separate `site-promote.yml` interface currently fails closed before downloading or changing anything: the actual Pages source and an exact-artifact deployment route must first be verified. A `GITHUB_TOKEN` push to `docs/` is not a deployment route, because it does not trigger a branch-based Pages build. Existing Pages source/environment protections remain authoritative; this change does not alter their settings. Expired or inconsistent artifacts must be rejected, not silently rebuilt.

External curation / cross-repository dispatcher implementations are retained as non-executing reference files under inactive-reference. Their workflow interfaces only explain that these actions are disabled in this fork; no token or content is sent. Restoring external communications requires a separately reviewed policy. Existing read-only contribution/security checks remain unchanged.

## Sync-only direction and conflict handling

This fork only receives upstream source. Do not prepare or submit upstream pull
requests, comments, code, registry notices, or cross-repository dispatches. Existing
branches, commits and draft PRs remain intact. Contribution validation describes
catalog safety checks inside this fork; it is not authorization to contribute
upstream, and failing checks must not be disabled to make synchronization green.

`downstream_repository` is the only permitted push destination. The script checks
every origin push URL and requires the configured non-default source branch before
any merge and again before a normal push. It never pushes main, tags or upstream.

The workflow snapshots the trusted default-branch policy SHA before checking out
the existing source branch. `preserve_local_paths` is an explicit reviewed
allowlist, not a blanket source-conflict override. Upstream additions and changes
under those paths are held and reported, including newly introduced workflows.
Other source files use an ordinary two-parent merge that retains both histories.
The latest trusted policy also refreshes an existing source branch when its source
is already current. Remote lookup failures stop instead of being mistaken for a
missing branch. No sync step builds, publishes, merges a PR or submits upstream.

Policy and source candidates are only activated after a separately authorized
merge into the default branch. A draft fix does not repair the currently scheduled
default-branch job by itself. This task does not authorize merging or publishing.
