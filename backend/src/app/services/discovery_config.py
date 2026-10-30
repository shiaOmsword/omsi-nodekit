"""Build reviewable YAML drafts from stored, endpoint-bound inventory."""

from app.entities import DeploymentTarget, DiscoverySelection, NodeFactory
from app.ports import JobRepository
from framework.entities import ValidationError, YamlCodec
from framework.messages import MessageKey
from framework.messages import text as message_text


class DiscoveryConfigService:
    def __init__(self, jobs: JobRepository, factory: NodeFactory, yaml_codec: YamlCodec):
        self.jobs = jobs
        self.factory = factory
        self.yaml = yaml_codec

    def suggest(self, request: DiscoverySelection):
        node = self.factory.from_yaml(request.yaml)
        job = self.jobs.details(request.job_id)
        report = job.report
        if (
            job.node_id != node.id
            or report is None
            or report.ssh_host != node.ssh.host
            or report.ssh_port != node.ssh.port
        ):
            raise ValidationError(message_text(MessageKey.DISCOVERY_SOURCE_MISMATCH))
        document = self.yaml.loads(request.yaml)
        panel = document.setdefault("panel", {})
        changes = []
        if report.panels:
            candidates = [p for p in report.panels if p.id == request.panel_id]
            if len(candidates) != 1:
                raise ValidationError(message_text(MessageKey.DISCOVERY_SELECTION_REQUIRED))
            found = candidates[0]
            panel.update(installation=found.installation, container=found.container)
            if found.service:
                panel["service"] = found.service
            if found.database_path:
                panel["database_path"] = found.database_path
            # Never transplant upstream defaults as if they had been observed.
            for setting, field in (
                ("webPort", "port"),
                ("webBasePath", "base_path"),
                ("subPort", "subscription_port"),
                ("subPath", "subscription_path"),
            ):
                if setting in found.settings and setting not in found.defaulted_settings:
                    value = found.settings[setting]
                    panel[field] = int(value) if field.endswith("port") else value
                    changes.append(f"panel.{field}")
            changes.append("panel.installation")
            # Existing panels remain read-only; do not attach a fresh deployment target.
            if found.installation != "managed":
                document.pop("deployment", None)
        else:
            if request.panel_id:
                raise ValidationError(message_text(MessageKey.DISCOVERY_SELECTION_REQUIRED))
            panel.update(installation="managed", container=None, database_path=None)
            target = DeploymentTarget(
                role=request.role, panel_runtime="native" if request.role == "exit" else "docker"
            )
            if request.caddy_id:
                candidates = [c for c in report.caddy if c.id == request.caddy_id]
                if len(candidates) != 1:
                    raise ValidationError(message_text(MessageKey.DISCOVERY_SELECTION_REQUIRED))
                caddy = candidates[0]
                bind = "127.0.0.1"
                if caddy.installation == "docker" and caddy.network_mode != "host":
                    if not caddy.host_gateway:
                        raise ValidationError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
                    bind = caddy.host_gateway
                target = DeploymentTarget(
                    role=request.role,
                    panel_runtime=target.panel_runtime,
                    caddy_mode="existing",
                    caddy_id=caddy.id,
                    subscription_bind=bind,
                )
                proxy = document.setdefault("caddy", {})
                if caddy.service:
                    proxy["service"] = caddy.service
                proxy["config_path"] = caddy.config_path
                if caddy.installation == "docker" and caddy.network_mode != "host":
                    for port in (2096, 443):
                        if any(p.endswith(f":{port}->{port}/tcp") for p in caddy.published_ports):
                            proxy["https_port"] = port
                            break
            document["deployment"] = target.model_dump(mode="json")
            document.setdefault("caddy", {})["enabled"] = target.caddy_mode != "none"
            changes.extend(["panel.installation", "deployment", "caddy.enabled"])
        updated = self.yaml.dumps(document)
        self.factory.from_yaml(updated)
        return {
            "yaml": updated,
            "changes": changes,
            "message": message_text(MessageKey.DISCOVERY_DRAFT_READY),
        }
