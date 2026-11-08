import json
from datetime import datetime, timezone

from framework.messages import MessageKey
from framework.messages import text as message_text

from .attach_caddy import attachment_status
from .caddy import CaddyInspector
from .discovery import SystemInventory
from .egress import routing_inventory
from .firewall import inspect_firewall, network_checks, public_firewall
from .panels import PanelInspector
from .preflight import PrerequisiteInspector
from .ssh_routes import exit_inventory
from .tcp_tuning import TCPConfigurator
from .xray_template import saved_routing_inventory


class InstallationInspector:
    def __init__(self, context):
        self.context = context
        self.inventory = SystemInventory(context)
        self.panels = PanelInspector(self.inventory)
        self.selected = None
        self.report = None

    def inspect(self):
        inventory = self.inventory
        containers = inventory.containers()
        findings = self.panels.discover(containers)
        self.selected = self.panels.select(findings)
        prerequisites = PrerequisiteInspector(self.context)
        capabilities = prerequisites.capabilities()
        self.report = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "ssh_host": self.context.node["ssh"]["host"],
            "ssh_port": self.context.node["ssh"]["port"],
            "panels": findings,
            "selected_panel": self.selected["id"] if self.selected else None,
            "caddy": CaddyInspector(inventory).discover(containers),
            "capabilities": capabilities,
            "profiles": prerequisites.profiles(capabilities),
            "warnings": list(dict.fromkeys(inventory.warnings)),
        }
        if self.selected and self.selected["installation"] == "managed":
            self.report["caddy_attachment"] = attachment_status(self.context)
        if not self.selected and len(findings) > 1:
            self.report["warnings"].append(message_text(MessageKey.INSPECTION_MULTIPLE))
        self.report["firewall"] = public_firewall(inspect_firewall(self.context))
        self.report["network_checks"] = network_checks(self.context, self.report)
        self.report["egress"] = routing_inventory(self.context, self)
        self.report["routing"] = saved_routing_inventory(self.context, self)
        self.report["ssh_exits"] = exit_inventory(self.context, self)
        self.report["tcp_tuning"] = TCPConfigurator(self.context).inspect()
        # Read-only systemd health; never claim that an active SSH process proves
        # VLESS authentication or actual egress return traffic.
        if capabilities.get("systemctl"):
            self.report["tunnels"] = [
                {
                    "name": t["name"],
                    "host": t["host"],
                    "ssh_port": t["ssh_port"],
                    "local_port": t["local_port"],
                    "target_port": t["target_port"],
                    "active": self.context.status(
                        ["systemctl", "is-active", "--quiet", self.context.unit(t["name"])]
                    )
                    == 0,
                    "enabled": self.context.status(
                        ["systemctl", "is-enabled", "--quiet", self.context.unit(t["name"])]
                    )
                    == 0,
                }
                for t in self.context.node["tunnels"][:24]
            ]
        self.publish()
        self.context.emit(message_text(MessageKey.INSPECTION_COMPLETED))
        return self.report

    def publish(self):
        print(json.dumps({"report": self.report}), flush=True)

    def database(self):
        return self.panels.database(self.selected)
