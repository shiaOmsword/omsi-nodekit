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
- SSH egress, independent session pools, shared balancers/routes, enable/disable and guarded restart controls.
- WireGuard inbound/peer management and identity-preserving import from 3x-ui and compatible wg-easy v15 SQLite snapshots.
- Private system backup archives and separate restoration of TCP settings and tunnel key files.
- BBR/CUBIC configuration and bounded ICMP/HTTPS network measurements.
- Protected panel HTTPS access through Caddy with Basic Auth or IP allowlists.
- Restore-target selection independent of the SQLite source runtime, with backup path validation.
- Subscription audits and explicit server-side cache maintenance for owned Docker panels.
- Public README in Russian and English, contributor/security documentation and issue templates.

### Documentation
- Reconciled first-run, deployment and transport instructions with `dev`; added a documentation index and GitBook navigation.

### Before the first release
- Validate fresh/restore on an isolated VPS and at least one live subscription from a test client.
- Review and choose an open-source license; audit the Git history for exposed infrastructure metadata/secrets.
- Promote the tested `dev` state to `main`; publish a versioned GitHub Release with supported topology and limitations.
