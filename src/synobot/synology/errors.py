"""Typed failures raised by the Synology Download Station client."""

from typing import Optional


class SynologyError(Exception):
    """Base class for all client failures."""

    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code


class SynologyConnectionError(SynologyError):
    pass


class SynologyTimeoutError(SynologyConnectionError):
    pass


class SynologyTlsError(SynologyConnectionError):
    pass


class SynologyAuthenticationError(SynologyError):
    pass


class SynologyOtpError(SynologyAuthenticationError):
    pass


class SynologyPermissionError(SynologyError):
    pass


class SynologySessionExpiredError(SynologyAuthenticationError):
    pass


class SynologyRateLimitError(SynologyError):
    pass


class SynologyApiError(SynologyError):
    pass
