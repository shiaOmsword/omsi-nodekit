"""Read-only host tooling inventory for future deployment variants.

A ready profile only means the currently-required tools are available.  It does
not authorize installation, establish port availability, or verify DNS/TLS.
"""

import os
import shutil
import sys

from framework.network.execute import ProcessError


class PrerequisiteInspector:
    def __init__(self, context):
        self.context = context

    def capabilities(self):
        tools = ("docker", "systemctl", "openssl", "ssh", "sudo", "curl", "tar", "caddy")
        found = {name: bool(shutil.which(name)) for name in tools}
        found["python3"] = sys.version_info >= (3, 11)
        found["root"] = bool(hasattr(os, "geteuid") and os.geteuid() == 0)
        found["docker_engine"] = False
        found["compose"] = False
        if found["docker"]:
            timeout = min(5, self.context.policy["command_timeout"])
            try:
                found["docker_engine"] = (
                    self.context.runner.status(
                        ["docker", "info", "--format", "{{.ServerVersion}}"], timeout=timeout
                    )
                    == 0
                )
                found["compose"] = (
                    self.context.runner.status(["docker", "compose", "version"], timeout=timeout)
                    == 0
                )
            except (ProcessError, OSError):
                pass
        return found

    def profiles(self, capabilities):
        profiles = []
        for panel in ("native", "docker"):
            for caddy in ("none", "native", "docker"):
                needed = {"python3", "root"}
                if panel == "native":
                    needed.update({"systemctl", "curl", "tar"})
                if panel == "docker" or caddy == "docker":
                    needed.update({"docker", "docker_engine", "compose"})
                if caddy == "native":
                    needed.update({"systemctl", "caddy"})
                if self.context.node.get("tunnels"):
                    needed.update({"systemctl", "ssh"})
                required = sorted(needed)
                missing = [name for name in required if not capabilities.get(name)]
                profiles.append(
                    {
                        "panel_runtime": panel,
                        "caddy_runtime": caddy,
                        "required": required,
                        "missing": missing,
                        "ready": not missing,
                    }
                )
        return profiles
