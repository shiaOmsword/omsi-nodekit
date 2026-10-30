import json
from pathlib import Path

from framework.database import SQLiteSnapshots
from framework.network.execute import CommandRunner


class AgentContext:
    def __init__(self, payload):
        self.payload = payload
        self.node = payload["node"]
        self.policy = payload["runtime"]["deployment"]
        self.limits = payload["runtime"]["limits"]
        self.snapshots = SQLiteSnapshots()
        self.runner = CommandRunner()

    def emit(self, message, level="info"):
        print(json.dumps({"message": message, "level": level}), flush=True)

    def command(self, args, timeout=None):
        return self.runner.run(
            args, timeout=timeout or self.policy["command_timeout"], sensitive="-password" in args
        )

    def status(self, args):
        return self.runner.status(args, timeout=self.policy["command_timeout"])

    def directory(self):
        return Path(self.policy["remote_root"]) / self.node["id"]

    def project(self):
        return f"{self.policy['service_prefix']}-{self.node['id']}"

    def unit(self, name):
        return f"{self.project()}-{name}.service"
