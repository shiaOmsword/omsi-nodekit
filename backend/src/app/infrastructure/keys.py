from app.ports import SSHKeyFiles
from framework.entities import InfrastructureError
from framework.network import OpenSSHKeys, ProcessError


class LocalSSHKeyFiles(SSHKeyFiles):
    def __init__(self, keys: OpenSSHKeys):
        self.keys = keys

    def generate(self, key_id):
        try:
            return self.keys.generate(key_id)
        except ProcessError as exc:
            raise InfrastructureError(str(exc)) from exc

    def identity(self, key_id):
        try:
            return self.keys.identity(key_id)
        except ProcessError as exc:
            raise InfrastructureError(str(exc)) from exc

    def remove(self, key_id):
        self.keys.remove(key_id)
