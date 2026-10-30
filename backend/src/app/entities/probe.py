from app.entities import StrictModel, Port, field_validator, re

class Probe(StrictModel):
    socks_port: Port = 10808
    url: str = "https://www.cloudflare.com/cdn-cgi/trace"

    @field_validator("url")
    @classmethod
    def https_url(cls, value: str) -> str:
        if not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?/[^\s]*", value):
            raise ValueError("Probe URL must be an HTTPS URL without credentials")
        return value