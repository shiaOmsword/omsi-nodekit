"""Only vetted catalogue messages may expose a concrete preflight failure."""


class TunnelPreflightError(ValueError):
    pass
