# Contributing to OMSI Nodekit

Thanks for helping improve the project. Nodekit is currently an **early-stage local administration tool**; its safeguards matter more than preserving a convenient but unsafe shortcut.

## Before opening a PR

For routine bugs or feature ideas, open an [Issue](https://github.com/shiaOmsword/omsi-nodekit/issues) or discuss the scope in an existing one. For vulnerabilities or exposed keys, **do not create a public issue**; follow [SECURITY.md](SECURITY.md).

Never commit or attach real client UUID/subId, VPN subscription URLs, node hostnames/IPs, SSH private keys, sudo passwords, `x-ui.db`, raw dumps, credentials.json, logs or `backend/data/`. Use placeholders such as `203.0.113.10` and `vpn.example.com`.

## Development setup

Install Python 3.12+, Poetry 2.x, Node.js 22.12+ (or compatible 24 LTS), npm and OpenSSH. See the [README](readme.md) for startup instructions.

```bash
cd frontend
npm ci
npm run build
cd ../backend
poetry install --with dev
poetry run nodekit
```

The local backend runs on http://127.0.0.1:8765 and serves the compiled frontend. For frontend-only development, run `npm run dev` inside `frontend/` in another terminal. Avoid backend autoreload during SSH operations.

## Branching and pull requests

1. Start a focused feature/fix/docs branch from **`dev`**. The `main` branch is the public release line and may lag.
2. Keep the patch within a cohesive scope; include a migration note if configuration or API contracts change.
3. Run lint, Python tests, frontend tests, and the frontend build locally when possible.
4. Open a PR targeting **`dev`**. Explain the use case, whether live VPS services are changed, ownership checks, rollback behavior, security considerations, and manual testing.
5. Wait for Ubuntu/Windows CI and review before merging. Never test destructive changes on someone else's VPS.

```bash
cd backend
poetry run ruff check src tests
poetry run ruff format --check src tests
poetry run pytest -q
cd ../frontend
npm test
npm run build
```

## Conventions

- Backend structure: `framework` contains shared infrastructure; `app/entities` contains validated models; `app/services` implements use cases; `app/infrastructure` and `app/agent` hold adapters and remote operations.
- Prefer explicit contracts, narrow ownership validation, preview/confirm/execute, structured errors and exact revision/fingerprint checks.
- Operations that touch a remote host must have regression tests for **foreign service protection**, duplicate runs, rollback and non-disclosure of secrets.
- Keep the GUI consistent with the existing React/TypeScript component library and Russian interface copy.
- Put public usage notes in `docs/`, examples in example files, and sensitive per-host runbooks **outside** the public repository.
- Avoid changing unrelated functionality or formatting an entire file without a reason.

## What helps reviewers

Share sanitized command output, relevant tests, an explanation of failure conditions and ideally screenshots using dummy accounts. Mark operations that could restart 3x-ui, alter UFW, Caddy, systemd, Docker networks or active client routing as **potentially disruptive**.

There is currently **no declared open-source license**. Public availability does not itself grant rights to redistribute the code. Until a license is selected, contact the maintainer before copying significant parts of the project into another work.
