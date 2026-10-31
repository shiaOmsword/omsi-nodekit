import json
from datetime import datetime, timezone

from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy import CaddyInspector
from .discovery import SystemInventory
from .panels import PanelInspector
from .preflight import PrerequisiteInspector


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
        if not self.selected and len(findings) > 1:
            self.report["warnings"].append(message_text(MessageKey.INSPECTION_MULTIPLE))
        self.publish()
        self.context.emit(message_text(MessageKey.INSPECTION_COMPLETED))
        return self.report

    def publish(self):
        print(json.dumps({"report": self.report}), flush=True)

    def database(self):
        return self.panels.database(self.selected)
