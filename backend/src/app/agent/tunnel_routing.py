import copy
import hashlib
import json
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .inbound_manager import managed_api
from .inbound_meta import public_inbound
from .ssh_routes import read_exit, refresh_route, verify_exit
from .tunnel_errors import TunnelPreflightError
from .tunnel_forward import TunnelForward
from .tunnel_manager import TunnelManager, private_write


class TunnelRouter:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        try:
            self._apply(base)
        except TunnelPreflightError as exc:
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            self.context.emit(
                message_text(MessageKey.TUNNEL_ERROR_TYPE, kind=type(exc).__name__), "error"
            )
            raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_FAILED)) from exc

    def _apply(self, base):
        context = self.context
        request = context.payload["options"]["tunnel_route"]
        api = managed_api(context, self.inspector, base)
        path, raw, record, names = read_exit(context, request["kind"], request["name"])
        if hashlib.sha256(raw).hexdigest() != request["expected_exit_fingerprint"]:
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_STALE))
        manager = TunnelManager(context, self.host, self.database, self.inspector)
        original = manager.template(api)
        inbounds = api.request("inbounds/list") or []
        record = refresh_route(record, inbounds)
        verify_exit(original, record)
        by_id = {i["id"]: public_inbound(i) for i in inbounds}
        selected = request["inbounds"]
        ids = [i["id"] for i in selected]
        if (
            not ids
            or len(ids) != len(set(ids))
            or any(
                i["id"] not in by_id
                or not by_id[i["id"]]["enabled"]
                or not by_id[i["id"]]["tag"]
                or by_id[i["id"]]["fingerprint"] != i["expected_fingerprint"]
                for i in selected
            )
        ):
            raise TunnelPreflightError(message_text(MessageKey.INBOUND_STALE))
        tags = [by_id[i]["tag"] for i in ids]
        added_tags = set(tags) - set(record["rule"]["inboundTag"])
        rules = original.get("routing", {}).get("rules", [])
        index = rules.index(record["rule"])
        if any(set(rule.get("inboundTag", [])) & added_tags for rule in rules[:index]):
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        tunnels = {t["name"]: t for t in context.node["tunnels"]}
        forwards = [TunnelForward(context, self.host, tunnels[name]) for name in names]
        for forward in forwards:
            forward.preflight(require_installed=True)
            if not forward.ready():
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_NOT_READY))
        outbounds = record["outbounds"] if "balancer" in record else [record["outbound"]]
        for outbound in outbounds:
            manager.probe(outbound)
        updated = copy.deepcopy(record)
        updated.update(inbound_ids=ids, inbound_id=ids[0])
        updated["rule"]["inboundTag"] = tags
        if "balancer" in updated:
            updated["inbound_tag"] = tags[0]
        proposed = copy.deepcopy(original)
        proposed["routing"]["rules"][index] = updated["rule"]
        # Keep the owned rule after the protected API/blackhole prefix, but do
        # not let an earlier catch-all silently bypass a newly selected inbound.
        protected = {
            o.get("tag") for o in original["outbounds"] if o.get("protocol") == "blackhole"
        }
        api_tag = (original.get("api") or {}).get("tag")
        if api_tag:
            protected.add(api_tag)
        if any(
            not r.get("inboundTag") and r.get("outboundTag") not in protected for r in rules[:index]
        ):
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        stamp = time.time_ns()
        self.database.snapshot(self.inspector.database(), base / f"before-tunnel-route-{stamp}.db")
        recovery = base / f"before-tunnel-route-{stamp}.json"
        private_write(recovery, json.dumps(original).encode())
        attempted, written = False, None
        try:
            latest = {i["id"]: public_inbound(i) for i in (api.request("inbounds/list") or [])}
            if (
                manager.template(api) != original
                or path.is_symlink()
                or path.read_bytes() != raw
                or any(latest.get(i) != by_id[i] for i in ids)
            ):
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_STALE))
            for forward in forwards:
                forward.preflight(require_installed=True)
                if not forward.ready():
                    raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_NOT_READY))
            if proposed != original:
                attempted = True
                api.request("xray/update", {"xraySetting": json.dumps(proposed)}, form=True)
                if manager.template(api) != proposed:
                    raise ValueError()
                api.request("server/restartXrayService", {})
            manager.wait(
                lambda: all(manager.runtime_matches(o, updated["rule"]) for o in outbounds)
            )
            for outbound in outbounds:
                manager.probe(outbound)
            if path.is_symlink() or path.read_bytes() != raw or manager.template(api) != proposed:
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_STALE))
            data = json.dumps(updated).encode()
            private_write(path, data)
            written = data
        except Exception:
            if attempted:
                try:
                    current = manager.template(api)
                    if current == proposed:
                        api.request("xray/update", {"xraySetting": json.dumps(original)}, form=True)
                        api.request("server/restartXrayService", {})
                        if manager.template(api) != original:
                            raise ValueError()
                    elif current != original:
                        raise ValueError()
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            if written is not None:
                try:
                    if path.is_symlink() or path.read_bytes() != written:
                        raise ValueError()
                    private_write(path, raw)
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise
        context.emit(
            message_text(MessageKey.TUNNEL_ROUTE_APPLIED, name=request["name"], count=len(ids))
        )
