from app.entities import Port, StrictModel, field_validator, re

class Panel(StrictModel):
    image: str = "ghcr.io/mhsanaei/3x-ui:3.11.0"
    port: Port = 2053
    base_path: str = "/nodekit/"
    subscription_port: Port = 2097
    subscription_path: str = "/sub/"

    @field_validator("base_path", "subscription_path")
    @classmethod
    def safe_url_path(cls, value: str) -> str:
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*", value):
            raise ValueError("Use a path such as /nodekit/ or /sub/")
        return value