# Security Policy

OMSI Nodekit is an early-stage, **local-first administrative application**. It can access SSH credentials, VPN client identities, 3x-ui databases and remotely managed services. Treat its local data directory and its host operating-system account as sensitive.

## Supported versions

The repository is in active 0.x development. There is currently **no formally supported release series or security response SLA**. The latest maintained code is developed on `dev`; the default `main` branch may lag until promoted. Please reproduce issues on the current code where possible.

## Reporting a vulnerability

**Please do not disclose a working exploit, private key, subscription URL, real VPS address, raw backup, or unredacted logs in a public GitHub Issue or PR.**

If the repository has GitHub **Private Vulnerability Reporting** enabled, open **Security → Report a vulnerability** to share details privately with the maintainer. Otherwise, contact the maintainer through an existing *private* channel before sharing exploit details; do not use a public Issue as a fallback. If a secret was exposed, revoke/rotate it promptly regardless of the report outcome.

A useful private report includes affected commit/version, local vs. remote component, reproduction steps using **synthetic test data**, expected vs. actual behavior, potential impact and any tested mitigation. Do not probe production nodes you do not own.

## Important boundaries

- **Local Nodekit API:** intended for `127.0.0.1`, not an Internet-facing multi-user service. Its local CSRF/host/origin checks are not a replacement for strong isolation from malicious processes running as the same OS user.
- **SSH credentials:** verify server host keys via a trusted source. Private keys, local `backend/data/` files and backups must be protected by filesystem permissions. A generated private key is not a public artifact.
- **Sudo secrets:** values placed in `ssh.sudo_password` are stored in local YAML/SQLite **without encryption**. Prefer `ssh.sudo_password_env` supplied to the local backend environment.
- **3x-ui databases:** SQLite snapshots can contain VLESS UUIDs, subscription tokens, REALITY keys and other sensitive material. Never upload them into issues, artifacts or public file-sharing.
- **Remote mutations:** respect Nodekit ownership boundaries. A generic running Docker container, Caddy site or native 3x-ui service must not be taken over or restarted solely because it shares a name or port.
- **Cache maintenance:** resetting the server cache restarts an explicitly verified Nodekit-owned Docker panel and **can interrupt live VPN clients**. It does not clear DNS or app caches on remote client devices.
- **Operational documentation:** public docs should use `example.com` and RFC 5737 TEST-NET addresses. Removing a secret from the newest commit does **not** erase it from the Git history; rotate compromised credentials, and consult GitHub support/guidance if history sanitization is necessary.

## Responsible testing

Use disposable VPS instances or mocks for potentially destructive tests. Do not assume a successful HTTP/TCP probe proves end-to-end VPN availability. For an incident, contain access first, snapshot relevant non-secret evidence, rotate affected credentials, and validate recovery in an isolated environment.

Security fixes and disclosures are coordinated by the maintainer as capacity allows. There is no bug bounty program or guarantee of response within a given time.
