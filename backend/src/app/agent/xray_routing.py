import copy
import json

from framework.messages import MessageKey
from framework.messages import text as message_text

from .egress import runtime_paths
from .inbound_meta import public_inbound
from .ssh_routes import read_exit, refresh_route
from .tunnel_errors import TunnelPreflightError
from .tunnel_manager import TunnelManager
from .xray_change import XrayChange, run_xray_operation
from .xray_template import add_balancer, editable_rule


def runtime_rule(rule):
    return {k: v for k, v in rule.items() if k not in {"enabled", "comment"}}


def route_template(original, request, inbounds):
    by_id = {i["id"]: public_inbound(i) for i in inbounds}
    selected = request["inbounds"]
    if any(
        i["id"] not in by_id
        or not by_id[i["id"]]["enabled"]
        or not by_id[i["id"]]["tag"]
        or by_id[i["id"]]["fingerprint"] != i["expected_fingerprint"]
        for i in selected
    ):
        raise TunnelPreflightError(message_text(MessageKey.INBOUND_STALE))
    tags = [by_id[i["id"]]["tag"] for i in selected]
    if len(set(tags)) != len(tags) or any(
        sum(i.get("tag") == tag for i in inbounds) != 1 for tag in tags
    ):
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    config = copy.deepcopy(original)
    routing = config.setdefault("routing", {})
    balancers = [b for b in routing.get("balancers", []) if b.get("tag") == request["balancer_tag"]]
    if len(balancers) != 1:
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    rules = routing.setdefault("rules", [])
    index = request.get("rule_index")
    api_tag = (config.get("api") or {}).get("tag")
    if index is not None and (index >= len(rules) or not editable_rule(rules[index], api_tag)):
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    old = rules[index] if index is not None else None
    for i, rule in enumerate(rules):
        if i == index or rule.get("enabled", True) is False:
            continue
        if editable_rule(rule, api_tag) and set(rule["inboundTag"]) & set(tags):
            raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
        if (index is None or i < index) and not rule.get("inboundTag"):
            conditions = set(rule) - {"type", "outboundTag", "balancerTag", "enabled", "comment"}
            if not conditions:
                raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    rule = {
        **(old or {}),
        "type": "field",
        "inboundTag": tags,
        "balancerTag": request["balancer_tag"],
    }
    rule.pop("outboundTag", None)
    if index is None:
        rules.append(rule)
    else:
        rules[index] = rule
    return config, old, rule


class XrayConfigurator(TunnelManager):
    def verify(self, proposed, *, rule=None, balancer=None):
        def matches():
            try:
                path, _ = runtime_paths(self.context, self.inspector)
                runtime = json.loads(path.read_text(encoding="utf-8"))
                routing = runtime.get("routing") or {}
                return (
                    (rule is None or runtime_rule(rule) in routing.get("rules", []))
                    and (
                        balancer is None
                        or [
                            b
                            for b in routing.get("balancers", [])
                            if b.get("tag") == balancer["tag"]
                        ]
                        == [balancer]
                    )
                    and all(
                        runtime.get(k) == proposed.get(k)
                        for k in ("outbounds", "observatory", "burstObservatory")
                    )
                )
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                return False

        try:
            self.wait(matches)
        except ValueError as exc:
            raise TunnelPreflightError(
                message_text(
                    MessageKey.TUNNEL_RUNTIME_FAILED,
                    config="readable_or_unavailable",
                    outbound="check_journal",
                    route="missing_or_different" if rule else "not_requested",
                    balancer="missing_or_different" if balancer else "not_requested",
                )
            ) from exc

    def apply(self, base):
        run_xray_operation(self, lambda: self._apply(base))

    def _apply(self, base):
        request = self.context.payload["options"]["xray"]
        self.stage("saved Xray template and selected resources")
        change = XrayChange(self, base, request["expected_fingerprint"])
        old = rule = balancer = None
        inbounds = []
        if request["operation"] == "balancer":
            proposed = add_balancer(
                change.original, request["tag"], request["members"], request["fallback_tag"]
            )
            balancer = next(
                b for b in proposed["routing"]["balancers"] if b["tag"] == request["tag"]
            )
        else:
            inbounds = change.api.request("inbounds/list") or []
            proposed, old, rule = route_template(change.original, request, inbounds)
        records = []
        if old:
            candidates = [("tunnel", t["name"]) for t in self.context.node["tunnels"]]
            candidates += [("pool", p.stem[5:]) for p in sorted(base.glob("pool-*.json"))[:100]]
            for kind, name in candidates:
                try:
                    path, raw, record, _ = read_exit(self.context, kind, name)
                    record = refresh_route(record, inbounds)
                except (OSError, ValueError, TypeError, KeyError, TunnelPreflightError):
                    continue
                if record.get("rule") != old:
                    continue
                target = record.get("balancer", record.get("outbound", {}))["tag"]
                if target == request["balancer_tag"] and "balancer" in record:
                    record.update(
                        rule=rule,
                        inbound_ids=[i["id"] for i in request["inbounds"]],
                        inbound_id=request["inbounds"][0]["id"],
                        inbound_tag=rule["inboundTag"][0],
                    )
                else:
                    record.update(rule=None, inbound_ids=[], inbound_id=None)
                records.append((path, raw, record))
        self.stage("private recovery snapshots and scoped Xray update")
        with change:
            if inbounds:
                latest = {
                    i["id"]: public_inbound(i) for i in (change.api.request("inbounds/list") or [])
                }
                if any(
                    latest.get(i["id"], {}).get("fingerprint") != i["expected_fingerprint"]
                    for i in request["inbounds"]
                ):
                    raise TunnelPreflightError(message_text(MessageKey.INBOUND_STALE))
            change.apply(proposed, lambda: self.verify(proposed, rule=rule, balancer=balancer))
            for path, raw, record in records:
                change.write(path, raw, record)
