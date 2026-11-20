# Contributing

## Flow

1. **Issue first.** Every change starts from a GitHub issue using a template (bug, feature,
   improvement). Label it with one `type:` and one `priority:` label.
2. **Branch** from `main`:
   - `feature/<issue#>-short-name`
   - `fix/<issue#>-short-name`
   - `chore/<issue#>-short-name` or `docs/<issue#>-short-name`
3. **Commit** in small, focused commits. Write the subject in the imperative
   ("Add watchlist toggle to film detail"), 72 characters max.
4. **Check** locally: `python manage.py test` and `python manage.py makemigrations --check --dry-run`.
5. **Pull request** into `main` using the template, with `Closes #<issue>`. CI runs analyze
   and tests. Merge with squash once checks and review are done.
6. **Docs**: update `docs/` and `CHANGELOG.md` in the same PR when behaviour changes.

## Labels

| Group | Labels |
|---|---|
| Type | `type: bug`, `type: feature`, `type: improvement`, `type: tech-debt`, `type: security`, `type: docs`, `type: chore` |
| Priority | `priority: P0 critical`, `priority: P1 high`, `priority: P2 medium`, `priority: P3 low` |
| Area | `area: accounts`, `area: films`, `area: takes`, `area: social`, `area: content`, `area: integrations`, `area: security`, `area: ci`, `area: api-contract` |
| Status | `status: needs triage`, `status: blocked`, `status: verified` |

## Versioning and releases

- [Semantic Versioning](https://semver.org). The API version is the git tag
  (`vX.Y.Z`).
- `CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com). Add entries under
  **Unreleased** in each PR.
- To release: move Unreleased entries under a new version heading,
  merge, then tag `vX.Y.Z` on `main` and publish a GitHub Release with the changelog
  section. The app is versioned and tagged independently.
