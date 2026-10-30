import os
import shutil
from datetime import datetime, timezone


class CertificateInspector:
    """Inspect public certificate metadata and readability, never the private key contents."""

    def __init__(self, inventory):
        self.inventory = inventory

    def inspect(self, usage, cert_path, key_path, resolve):
        result = {
            "usage": usage,
            "cert_path": cert_path,
            "key_path": key_path,
            "state": "not_configured",
            "key_readable": None,
        }
        if not cert_path and not key_path:
            return result
        cert, key = resolve(cert_path), resolve(key_path)
        result["key_readable"] = bool(key and key.is_file() and os.access(key, os.R_OK))
        if not cert or not cert.is_file() or not result["key_readable"]:
            result["state"] = "missing"
            return result
        result["state"] = "unknown"
        if not shutil.which("openssl"):
            return result
        try:
            output = self.inventory.command(
                [
                    "openssl",
                    "x509",
                    "-in",
                    str(cert),
                    "-noout",
                    "-startdate",
                    "-enddate",
                    "-fingerprint",
                    "-sha256",
                ]
            )
            values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            start = datetime.strptime(values["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc
            )
            end = datetime.strptime(values["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc
            )
            now = datetime.now(timezone.utc)
            result.update(
                not_before=start.isoformat(),
                not_after=end.isoformat(),
                sha256=next((v for k, v in values.items() if "fingerprint" in k.lower()), None),
                state="expired" if end <= now else "not_yet_valid" if start > now else "valid",
            )
        except (RuntimeError, ValueError, KeyError):
            result["state"] = "invalid"
        return result
