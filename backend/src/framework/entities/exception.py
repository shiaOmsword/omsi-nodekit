class ApplicationError(Exception):
    code = "application_error"

    def __init__(self, message: str, *, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ValidationError(ApplicationError):
    code = "validation_error"


class NotFoundError(ApplicationError):
    code = "not_found"


class ConflictError(ApplicationError):
    code = "conflict"


class PayloadTooLargeError(ApplicationError):
    code = "payload_too_large"


class InfrastructureError(ApplicationError):
    code = "infrastructure_error"


class ConfigurationError(ApplicationError):
    code = "configuration_error"
