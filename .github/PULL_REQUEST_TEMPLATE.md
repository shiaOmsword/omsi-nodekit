## What and why

Summarize the problem solved and the main implementation changes.

## Scope

- [ ] Backend / API / remote agent
- [ ] Frontend / UX
- [ ] Documentation / configuration / tests
- [ ] This can modify a running VPS or active VPN connections

## Safety review

- [ ] No real hostnames, IPs, private keys, UUID/subId, backup files, passwords or raw production logs
- [ ] Ownership / revision / fingerprint checks preserved or strengthened
- [ ] For server mutations: plan, explicit confirmation, backup and rollback/failure behavior documented
- [ ] Shared Caddy / Docker / native services outside Nodekit ownership remain untouched
- [ ] No silent fallback to insecure TLS, unverified host keys or unexpected direct routing

## Verification

- [ ] `poetry run ruff check src tests`
- [ ] `poetry run ruff format --check src tests`
- [ ] `poetry run pytest -q`
- [ ] `npm test`
- [ ] `npm run build`
- [ ] Live test on a disposable VPS, if relevant (**optional; document scope and result**)

**Testing notes / related issue:**

**User-facing behavior and docs updated:**

**Rollback / residual risks:**
