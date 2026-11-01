from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy_ports import CaddyPortsTransaction
from .firewall import FirewallTransaction, desired_rules, reserved_caddy_ports
from .inspection import InstallationInspector


class NodeNetwork:
    def __init__(self, context, inspector, base):
        self.context, self.inspector = context, inspector
        target = context.node.get("deployment") or {}
        self.firewall = FirewallTransaction(context, base, enabled=target.get("manage_ufw", True))
        self.ports = CaddyPortsTransaction(context, inspector)

    def prepare(self):
        self.ports.prepare()

    def allow(self, extra=()):
        self.firewall.ensure(desired_rules(self.context, self.inspector.report, extra=extra))

    def publish(self):
        if self.ports.apply():
            self.inspector = InstallationInspector(self.context)
            self.inspector.inspect()
            return True
        return False

    def commit(self, host):
        if not self.firewall.enabled or self.firewall.finding["state"] != "active":
            return
        observed = InstallationInspector(self.context)
        observed.inspect()
        ports = {
            i["port"]
            for p in observed.report["panels"]
            for i in p.get("inbounds", [])
            if i["enabled"]
        }
        ports.update(reserved_caddy_ports(observed.report))
        for proxy in observed.report["caddy"]:
            for publication in proxy.get("published_ports", []):
                try:
                    ports.add(int(publication.rsplit("->", 1)[0].rsplit(":", 1)[1]))
                except (ValueError, IndexError):
                    pass
        self.firewall.prune(ports, host)
        self.firewall.commit()

    def rollback(self):
        for callback in (self.ports.rollback, self.firewall.rollback):
            try:
                callback()
            except Exception:
                self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
