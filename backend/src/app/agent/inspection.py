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
            "panels": findings,
            "selected_panel": self.selected["id"] if self.selected else None,
            "caddy": CaddyInspector(inventory).discover(containers),
            "capabilities": capabilities,
            "profiles": prerequisites.profiles(capabilities),
            "warnings": list(dict.fromkeys(inventory.warnings)),
        }
        if not self.selected and len(findings) > 1:
            self.report["warnings"].append(message_text(MessageKey.INSPECTION_MULTIPLE))
        print(json.dumps({"report": self.report}), flush=True)
        self.context.emit(message_text(MessageKey.INSPECTION_COMPLETED))
        return self.report

    def database(self):
        return self.panels.database(self.selected)
