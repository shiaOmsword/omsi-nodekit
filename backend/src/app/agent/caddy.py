import json
import re
import shlex
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text


class CaddyInspector:
    def __init__(self, inventory):
        self.inventory = inventory

    @staticmethod
    def _flag(args, name):
        for index, value in enumerate(args):
            if value.startswith(name + "="):
                return value.split("=", 1)[1]
            if value == name and index + 1 < len(args):
                return args[index + 1]
        return None

    def _routes(self, config):
        """Whitelist route topology only: never expose headers, auth, DNS tokens or raw JSON."""
        output = []
        maximum = self.inventory.policy["max_routes"]

        def address(value):
            if not isinstance(value, str):
                return None
            # Upstream URLs must not disclose embedded credentials or query parameters.
            if "://" in value:
                parsed = urlsplit(value)
                return f"{parsed.scheme}://{parsed.hostname or ''}" + (
                    f":{parsed.port}" if parsed.port else ""
                )
            return value if "@" not in value and "?" not in value else None

        def walk(routes, listen, hosts=(), paths=(), depth=0):
            if depth > 20 or len(output) >= maximum:
                return
            for route in routes:
                if not isinstance(route, dict):
                    continue
                matches = route.get("match", [])
                route_hosts = sorted(
                    {h for m in matches for h in m.get("host", []) if isinstance(h, str)}
                ) or list(hosts)
                route_paths = sorted(
                    {p for m in matches for p in m.get("path", []) if isinstance(p, str)}
                ) or list(paths)
                for handler in route.get("handle", []):
                    if handler.get("handler") == "reverse_proxy" or not handler.get("routes"):
                        upstreams = [address(u.get("dial")) for u in handler.get("upstreams", [])]
                        output.append(
                            {
                                "listen": listen,
                                "hosts": route_hosts,
                                "paths": route_paths,
                                "upstreams": [u for u in upstreams if u],
                            }
                        )
                        if len(output) >= maximum:
                            return
                    walk(handler.get("routes", []), listen, route_hosts, route_paths, depth + 1)

        for server in config.get("apps", {}).get("http", {}).get("servers", {}).values():
            start = len(output)
            walk(server.get("routes", []), server.get("listen", []))
            if len(output) == start and len(output) < maximum:
                output.append(
                    {"listen": server.get("listen", []), "hosts": [], "paths": [], "upstreams": []}
                )
        return output

    def _config(self, finding, args, container=None):
        override = self.inventory.context.node["caddy"].get("config_path")
        path = override or self._flag(args, "--config") or self._flag(args, "-c")
        if not path and not any(value in {"--resume", "-r"} for value in args):
            path = self.inventory.policy["caddy_config"]
        finding.update(config_path=path, config_source="unavailable", routes=[], warnings=[])
        if not path or not (PurePosixPath(path).is_absolute() or Path(path).is_absolute()):
            finding["warnings"].append(message_text(MessageKey.INSPECTION_CADDY_UNSUPPORTED))
            return
        resolve = (lambda p: self.inventory.container_path(container, p)) if container else Path
        source = resolve(path)
        try:
            config = None
            if source and source.is_file():
                if source.stat().st_size > self.inventory.maximum:
                    raise ValueError(message_text(MessageKey.INSPECTION_TOO_LARGE))
                try:
                    config = json.loads(source.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            if config is None:
                adapter = self._flag(args, "--adapter") or self._flag(args, "-a") or "caddyfile"
                command = ["caddy", "adapt", "--config", path, "--adapter", adapter]
                if container:
                    if not finding["active"]:
                        raise RuntimeError(message_text(MessageKey.INSPECTION_CADDY_FAILED))
                    command = ["docker", "exec", container["Id"], *command]
                elif not shutil.which("caddy"):
                    raise RuntimeError(message_text(MessageKey.INSPECTION_CADDY_FAILED))
                config = json.loads(self.inventory.command(command))
            finding["routes"] = self._routes(config)
            finding["config_source"] = "file"
            finding["warnings"].append(message_text(MessageKey.INSPECTION_CADDY_FILE))
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError, KeyError):
            finding["warnings"].append(message_text(MessageKey.INSPECTION_CADDY_FAILED))
        if container and finding.get("network_mode") != "host":
            finding["warnings"].append(message_text(MessageKey.INSPECTION_CADDY_NETWORK))

    def discover(self, containers):
        result = []
        service_name = self.inventory.context.node["caddy"]["service"]
        service = self.inventory.service(service_name)
        if service:
            finding = {
                "id": f"native:{service_name}",
                "installation": "native",
                "service": service_name,
                "active": service.get("ActiveState") == "active",
            }
            command = service.get("ExecStart", "")
            match = re.search(r"argv\[\]=(.*?)(?: ;| })", command)
            try:
                args = shlex.split(match.group(1) if match else command)
            except ValueError:
                args = []
            self._config(finding, args)
            result.append(finding)
        for container in containers:
            details = self.inventory.describe_container(container)
            name = details["container"].lower()
            image = details["image"].rsplit("/", 1)[-1].split(":", 1)[0].lower()
            command = container.get("Config", {}).get("Cmd") or []
            if image != "caddy" and "caddy" not in name and "caddy" not in command:
                continue
            finding = {"id": f"docker:{container['Id']}", "installation": "docker", **details}
            gateways = {
                n.get("Gateway")
                for n in container.get("NetworkSettings", {}).get("Networks", {}).values()
                if n.get("Gateway")
            }
            finding["host_gateway"] = next(iter(gateways)) if len(gateways) == 1 else None
            self._config(finding, command, container)
            result.append(finding)
        return result
