from app.entities import StrictModel, Literal, Field
class JobRequest(StrictModel):
    action: Literal["check", "doctor", "fresh", "restore", "backup"]
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: str