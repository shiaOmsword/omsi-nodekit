from framework.messages import ErrorCode


class ApplicationError(Exception):
    code = ErrorCode.APPLICATION_ERROR

    def __init__(self, message: str, *, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ValidationError(ApplicationError):
    code = ErrorCode.VALIDATION_ERROR


class NotFoundError(ApplicationError):
    code = ErrorCode.NOT_FOUND


class ConflictError(ApplicationError):
    code = ErrorCode.CONFLICT


class PayloadTooLargeError(ApplicationError):
    code = ErrorCode.PAYLOAD_TOO_LARGE


class InfrastructureError(ApplicationError):
    code = ErrorCode.INFRASTRUCTURE_ERROR


class ConfigurationError(ApplicationError):
    code = ErrorCode.CONFIGURATION_ERROR
