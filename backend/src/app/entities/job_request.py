from pydantic import Field

from .base import StrictModel
from .records import JobAction


class JobRequest(StrictModel):
    action: JobAction
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
