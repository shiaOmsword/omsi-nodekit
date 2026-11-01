# Changelog

Notable user-visible changes to OMSI Nodekit will be documented here.

There is **no tagged GitHub Release yet**. Items below reflect work present on the development branch; they are not a promise that a particular released `main` commit contains every feature.

## Unreleased

### Added
- Local FastAPI + React control plane and SSH execution with explicit plans and job logs.
- Native/Docker 3x-ui discovery, Caddy/TLS/network inspection and diagnostics.
- Managed fresh provisioning, consistent SQLite backups and guarded restore.
- Supported VLESS/REALITY inbound and client operations; selective UUID/subId-preserving import.
- XHTTP/TLS ingress with Caddy ownership checks and supported Hosts publication.
- SSH egress, multiple sessions, guarded Xray routing and diagnostics.
- Subscription audits and explicit server-side cache maintenance for owned Docker panels.
- Public README in Russian and English, contributor/security documentation and issue templates.

### Before the first release
- Validate fresh/restore on an isolated VPS and at least one live subscription from a test client.
- Review and choose an open-source license; audit the Git history for exposed infrastructure metadata/secrets.
- Promote the tested `dev` state to `main`; publish a versioned GitHub Release with supported topology and limitations.
