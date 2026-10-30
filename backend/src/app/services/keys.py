from app.entities import NodeFactory, SSHKey, SSHKeyRequest
from app.ports import JobRepository, NodeRepository, SSHKeyFiles, SSHKeyRepository
from framework.entities import ConflictError
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import new_id


class SSHKeyService:
    def __init__(
        self,
        keys: SSHKeyRepository,
        files: SSHKeyFiles,
        nodes: NodeRepository,
        factory: NodeFactory,
        jobs: JobRepository,
    ):
        self.keys = keys
        self.files = files
        self.nodes = nodes
        self.factory = factory
        self.jobs = jobs

    def list(self):
        return self.keys.list()

    def create(self, request: SSHKeyRequest):
        key_id = new_id()
        public, fingerprint = self.files.generate(key_id)
        try:
            return self.keys.save(
                SSHKey(id=key_id, name=request.name, public_key=public, fingerprint=fingerprint)
            )
        except Exception:
            self.files.remove(key_id)
            raise

    def require(self, key_id):
        self.keys.get(key_id)
        return self.files.identity(key_id)

    def delete(self, key_id):
        self.keys.get(key_id)
        if any(job.status in {"queued", "running"} for job in self.jobs.list()):
            raise ConflictError(message_text(MessageKey.SSH_KEY_JOB_RUNNING))
        for summary in self.nodes.list():
            node = self.factory.from_yaml(self.nodes.get(summary.id).yaml)
            if node.ssh.key_id == key_id:
                raise ConflictError(message_text(MessageKey.SSH_KEY_IN_USE))
        self.files.remove(key_id)
        self.keys.delete(key_id)
