"""Typed Synology Download Station API."""

from .client import SynologyClient
from .errors import (
    SynologyApiError,
    SynologyAuthenticationError,
    SynologyConnectionError,
    SynologyError,
    SynologyOtpError,
    SynologyPermissionError,
    SynologyRateLimitError,
    SynologySessionExpiredError,
    SynologyTimeoutError,
    SynologyTlsError,
)
from .models import Task, TransferStats

__all__ = [
    "SynologyClient",
    "Task",
    "TransferStats",
    "SynologyError",
    "SynologyApiError",
    "SynologyAuthenticationError",
    "SynologyConnectionError",
    "SynologyOtpError",
    "SynologyPermissionError",
    "SynologyRateLimitError",
    "SynologySessionExpiredError",
    "SynologyTimeoutError",
    "SynologyTlsError",
]
