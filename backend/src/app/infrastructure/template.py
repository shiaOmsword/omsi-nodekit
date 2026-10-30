from app.config import Settings
from app.ports import NodeTemplate
from framework.entities import ConfigurationError


class FileNodeTemplate(NodeTemplate):
    def __init__(self, settings: Settings):
        self.path = settings.template_file

    def read(self):
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError("Node template is not available") from exc
