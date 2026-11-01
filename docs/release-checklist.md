# First public release checklist

This is a release preparation checklist, **not** evidence that a release has already been shipped.

## Repository

- [ ] Select and commit an explicit open-source LICENSE, or document intentionally proprietary terms.
- [ ] Review `readme.md`, `README.en.md`, `SECURITY.md` and `CONTRIBUTING.md`.
- [ ] Set About description, repository topics and (if available) a public demo link.
- [ ] Enable private vulnerability reporting and security alerts in GitHub Settings.
- [ ] Configure branch rules: protected `main`, required passing CI for PRs, no force push.
- [ ] Consider secret scanning / push protection where available.
- [ ] Inspect **entire Git history** for exposed credentials. Deleting lines in a new commit does not remove history; revoke secrets regardless of rewriting history.

## Product

- [ ] Run `ruff`, backend tests, frontend tests and build on Linux/Windows for the **exact release commit**.
- [ ] Perform manual read-only discovery on a test VPS.
- [ ] Perform one fresh/restore rehearsal on a disposable VPS using a test database.
- [ ] Confirm real DNS, HTTPS and subscription output with a test client.
- [ ] Confirm ownership guards: shared Caddy and manually installed services remain untouched.
- [ ] Verify that logs, screenshots, docs and release assets contain no real subId/UUID/private credentials.
- [ ] Update README's feature matrix and document unsupported installation/topology versions.

## Release

- [ ] Choose a semantic pre-release tag such as `v0.1.0-beta.1` (do not reuse already published tags).
- [ ] Merge the reviewed dev branch into `main` according to the project's PR workflow.
- [ ] Create a GitHub Release with changelog, requirements, supported 3x-ui version, security limitations and migration notes.
- [ ] Keep it a pre-release until installation/rollback behavior is reliable.
- [ ] Link the new release from README; consider distributing signed binaries/installers only after a separate packaging and trust review.

Avoid GitHub auto-generated releases that imply the app is production-ready without the above checks.
