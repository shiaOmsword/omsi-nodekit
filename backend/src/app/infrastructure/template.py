from app.config import Settings
from app.ports import NodeTemplate
from framework.entities import ConfigurationError
from framework.messages import MessageKey
from framework.messages import text as message_text


class FileNodeTemplate(NodeTemplate):
    def __init__(self, settings: Settings):
        self.path = settings.template_file

    def read(self):
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(message_text(MessageKey.TEMPLATE_UNAVAILABLE)) from exc
