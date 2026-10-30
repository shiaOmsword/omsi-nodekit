# Nodekit deployment topologies — design and rollout plan

This is a design contract, **not** a claim that native and hybrid deployments are
already executable. The current `panel.installation: managed` means Nodekit-owned
Docker Compose and must remain backward compatible. Existing `native`, `docker`,
and `auto` mean *discovery*, not a fresh-install target.

## Target matrix

| New 3x-ui | New Caddy | Remote prerequisites | Notes |
| --- | --- | --- | --- |
| native | native | Python 3.11+, root/sudo, systemd, curl, tar, native Caddy install | both services managed by systemd |
| docker | docker | Python 3.11+, root/sudo, working Docker Engine + Compose | use isolated Nodekit-owned Compose project |
| docker | native | requirements of both | Caddy reverse-proxies only the configured HTTP listeners |
| native | docker | requirements of both | Docker Caddy can use a host-published upstream or an explicitly selected network |
| native/docker | none | requirements for selected 3x-ui runtime | direct/SSH-tunneled management; no Caddy needed |

The read-only preflight report now shows whether *tools exist today* for all six
runtime profiles. It does **not** install missing tools, open firewalls, reserve
ports, verify public DNS, or decide ownership of existing services.

## Planned configuration (not accepted by current API)

```yaml
deployment:
  target:
    panel: docker             # docker | native
    caddy: none              # none | native | docker
  subscription_domain: null # explicit domain only if public HTTPS subscriptions needed
  inbounds:
    - protocol: vless
      port: 443
      security: reality
    - protocol: vless
      port: 8443
      security: reality
```

Do **not** overload existing `panel.installation` with this target specification.
The final inbound specification must also model Reality keys, SNI/target,
transport, unique inbound tags, and any Xray routing. A Reality camouflage SNI
is **not** the same thing as a DNS name pointing to the subscription server.

## Safe installation workflow

1. **Discover** OS, CPU architecture, current systemd services, Docker/Compose,
   installed 3x-ui/Caddy, listening TCP/UDP ports, firewall, CA material, and
   the existing remote directory. Capture a read-only report.
2. **Plan** exact owned resources: requested native service units or Compose
   project, chosen panel/subscription ports and paths, inbound ports, Caddy
   upstream addresses, and certificate issuance strategy.
3. **Preflight** privileges, missing tools, file collisions and active sockets
   (including IPv6 and TCP/UDP). Identify whether an occupied port belongs
   to an existing, selected installation. Never assume a free-port probe
   reserves a port; recheck immediately before starting services.
4. **Approve/apply**: pinned image digests or verified release archives, no
   unreviewed execution of `curl | bash`; write only Nodekit-owned directories,
   units, networks, and configs. Native service installation needs a separate
   tested adapter and rollback path.
5. **Configure** HTTP panel/subscription upstreams, optional Caddy and public
   domain, then provision optional VLESS inbounds via the **authenticated
   3x-ui API**, not raw SQL writes to a version-dependent schema.
6. **Verify** systemd/container health, local connections, authenticated TLS,
   public subscription URL if configured, and an optional real VLESS client
   transport check. Persist structured events in the job journal.

If port 443 is used for Xray/REALITY, ordinary Caddy HTTP reverse_proxy
**cannot** share that raw TCP listener. Choose separate Caddy HTTPS port
(or a consciously configured transport multiplexer, outside initial scope).

## Restore semantics

- A SQLite snapshot restores **existing inbounds and clients**. Never insert
  default 443/8443 inbounds on top of a restored database.
- The user's inspected backup contains VLESS ports **443 and 8443**; it does
  not show port 8433. All future ports must remain configurable and be
  checked against both the saved database and live host.
- Restoration must respect the 3x-ui schema/image version; validate
  compatibility and refuse unknown migrations, rather than silently upgrading
  production clients.
- The SQLite file is sensitive: it contains identities, inbound settings and
  potentially private material. Certificates, external private keys, Caddy
  state, systemd units, and other host files may live **outside** SQLite.
  A reliable whole-node recovery therefore needs an additional explicit,
  encrypted backup bundle and verified restoration steps.
- The current Nodekit Docker restore deliberately rewrites panel/subscription
  listeners to localhost and clears their built-in TLS file paths; this
  is *not* a byte-for-byte restoration of the old public HTTPS environment.

## Access and safety

- Current Nodekit authenticates SSH using a **key**; `sudo_password` is for
  privilege escalation after key login. Root SSH password authentication is
  not implemented and should not become the default.
- Administrator UI without a public domain should stay on loopback and be
  accessed with SSH port forwarding. Optional public subscription HTTPS
  needs a valid certificate and a hostname matching its URL.
- `check`, `doctor`, and `backup` must remain read-only on the VPS.
- `archive` / local `delete` of a Nodekit record must never stop or delete
  a remote 3x-ui/Caddy installation.
