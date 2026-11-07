import json

from framework.messages import MessageKey
from framework.messages import text as message_text

from .ssh_routes import read_exit
from .tunnel_errors import TunnelPreflightError
from .tunnel_forward import TunnelForward
from .tunnel_manager import loopback_outbound, routed_template
from .xray_change import XrayChange, run_xray_operation
from .xray_routing import XrayConfigurator
from .xray_template import add_balancer


class TunnelSetup(XrayConfigurator):
    def apply(self, base):
        run_xray_operation(self, lambda: self._setup(base))

    def _setup(self, base):
        context = self.context
        request = context.payload["options"]["tunnel_setup"]
        configured = {t["name"]: t for t in context.node["tunnels"]}
        names = request["names"]
        if not names or len(names) != len(set(names)) or not set(names) <= configured.keys():
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        self.stage("SSH resources and saved Xray template")
        change = XrayChange(self, base, request["expected_fingerprint"])
        proposed = change.original
        records, outbounds, forwards = [], [], []
        for name in names:
            tunnel = configured[name]
            path = base / f"tunnel-{name}.json"
            if path.is_symlink() or (
                path.exists() and path.stat().st_size > context.discovery["metadata_bytes"]
            ):
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            if path.exists():
                raw = path.read_bytes()
                saved = json.loads(raw)
                if saved.get("pooled_into"):
                    _, _, pool, members = read_exit(context, "pool", saved["pooled_into"])
                    outbound = pool["outbounds"][members.index(name)]
                else:
                    _, _, saved, _ = read_exit(context, "tunnel", name)
                    outbound = saved["outbound"]
                if [o for o in proposed["outbounds"] if o.get("tag") == outbound["tag"]] != [
                    outbound
                ] or loopback_outbound(outbound, outbound["tag"], tunnel["local_port"]) != outbound:
                    raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            else:
                tag = f"ssh-{context.node['id']}-{name}"
                if any(
                    tag.startswith(s)
                    for b in (proposed.get("routing") or {}).get("balancers", [])
                    for s in b.get("selector", [])
                ):
                    raise TunnelPreflightError(message_text(MessageKey.XRAY_SELECTOR_CONFLICT))
                proposed, outbound, _ = routed_template(
                    proposed, request["outbound_tag"], tunnel, tag, None
                )
                records.append(
                    (
                        path,
                        None,
                        {
                            "outbound": outbound,
                            "rule": None,
                            "inbound_id": None,
                            "inbound_ids": [],
                            "source_tag": request["outbound_tag"],
                        },
                    )
                )
            outbounds.append(outbound)
            forward = TunnelForward(context, self.host, tunnel)
            forward.preflight(require_installed=forward.path.exists())
            forwards.append(forward)
        if request.get("balancer_tag"):
            proposed = add_balancer(
                proposed,
                request["balancer_tag"],
                [o["tag"] for o in outbounds],
                request["fallback_tag"],
            )
        manifest_path = base / "manifest.json"
        if manifest_path.is_symlink():
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
        applied = {t["name"]: t for t in manifest["node"]["tunnels"]}
        applied.update({name: configured[name] for name in names})
        manifest["node"]["tunnels"] = list(applied.values())
        try:
            with change:
                self.stage("SSH authentication, loopback forwarding and HTTPS")
                for forward, outbound in zip(forwards, outbounds):
                    forward.preflight(require_installed=forward.path.exists())
                    forward.start()
                    self.wait(forward.ready)
                    self.probe(outbound)
                self.stage("Xray outbound and balancer runtime verification")
                balancer = next(
                    (
                        b
                        for b in (proposed.get("routing") or {}).get("balancers", [])
                        if b.get("tag") == request.get("balancer_tag")
                    ),
                    None,
                )
                change.apply(
                    proposed, lambda: self.verify(proposed, outbounds=outbounds, balancer=balancer)
                )
                for outbound in outbounds:
                    self.verify_return_traffic(outbound)
                for path, raw, record in records:
                    change.write(path, raw, record)
                change.write(manifest_path, raw_manifest, manifest)
        except Exception:
            if change.safe_to_stop:
                for forward in reversed(forwards):
                    try:
                        forward.rollback()
                    except Exception:
                        context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise
