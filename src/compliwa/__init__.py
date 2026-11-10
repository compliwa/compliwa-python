"""The official Python library for the Compliwa API.

from compliwa import Compliwa

client = Compliwa()   # reads COMPLIWA_API_KEY: cw_test_… (sandbox) or cw_live_…
verification = client.verifications.create({"check": "NG:NIN", "id_number": "12345678901", "consent": True})
"""

from ._client import AsyncCompliwa, Compliwa
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    CompliwaError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    WebhookSignatureError,
)
from ._generated.meta import API_VERSION, OPERATIONS
from ._options import RequestOptions
from ._pagination import AsyncPage, AsyncPaginator, RangeError, SyncPage
from ._response import LastResponse, get_last_response
from ._version import VERSION
from ._webhooks import SIGNATURE_HEADER, sign_webhook, verify_webhook

__version__ = VERSION

__all__ = [
    "API_VERSION",
    "OPERATIONS",
    "SIGNATURE_HEADER",
    "VERSION",
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AsyncCompliwa",
    "AsyncPage",
    "AsyncPaginator",
    "AuthenticationError",
    "Compliwa",
    "CompliwaError",
    "ConflictError",
    "InvalidRequestError",
    "LastResponse",
    "NotFoundError",
    "PermissionDeniedError",
    "RangeError",
    "RateLimitError",
    "RequestOptions",
    "SyncPage",
    "WebhookSignatureError",
    "get_last_response",
    "sign_webhook",
    "verify_webhook",
]
