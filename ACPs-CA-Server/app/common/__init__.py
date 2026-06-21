"""
公共模块

包含多个功能模块共享的模型、服务、模式等组件。
"""

from .certificate_model import (
    Certificate,
    CertificateStatus,
    CertificateType,
    RevocationReason,
)
from .certificate_service import CertificateService
from .certificate_schema import (
    CertificateBase,
    CertificateCreate,
    CertificateUpdate,
    CertificateResponse,
    CertificateListResponse,
    PagedResponse,
    ErrorResponse,
    CreateRootCertificateRequest,
    CreateIntermediateCertificateRequest,
)

# CRL相关
from .crl_model import CRL, CRLStatus, RevokedCertificateEntry
from .crl_service import CRLService
from .crl_schema import (
    CRLInfoResponse,
    CRLDistributionPointsResponse,
    RevokedCertificateInfo,
    CRLCreateRequest,
    CRLResponse,
    CRLListResponse,
)

# OCSP相关
from .ocsp_model import (
    OCSPRequest,
    OCSPResponse,
    OCSPResponder,
    OCSPResponseStatus,
)
from .ocsp_service import OCSPService
from .ocsp_schema import (
    OCSPSingleRequest,
    OCSPBatchRequest,
    OCSPSingleResponse,
    OCSPBatchResponse,
    OCSPResponderInfo,
    OCSPCreateResponderRequest,
    OCSPResponderResponse,
    OCSPStatsResponse,
)

from .time_utils import (
    beijing_now,
    beijing_end_of_day,
    format_datetime,
    is_expired,
    days_until_expiry,
)

__all__ = [
    # Certificate Models
    "Certificate",
    "CertificateStatus",
    "CertificateType",
    "RevocationReason",
    # Certificate Services
    "CertificateService",
    # Certificate Schemas
    "CertificateBase",
    "CertificateCreate",
    "CertificateUpdate",
    "CertificateResponse",
    "CertificateListResponse",
    "PagedResponse",
    "ErrorResponse",
    "CreateRootCertificateRequest",
    "CreateIntermediateCertificateRequest",
    # CRL Models
    "CRL",
    "CRLStatus",
    "RevokedCertificateEntry",
    # CRL Services
    "CRLService",
    # CRL Schemas
    "CRLInfoResponse",
    "CRLDistributionPointsResponse",
    "RevokedCertificateInfo",
    "CRLCreateRequest",
    "CRLResponse",
    "CRLListResponse",
    # OCSP Models
    "OCSPRequest",
    "OCSPResponse",
    "OCSPResponder",
    "OCSPResponseStatus",
    # OCSP Services
    "OCSPService",
    # OCSP Schemas
    "OCSPSingleRequest",
    "OCSPBatchRequest",
    "OCSPSingleResponse",
    "OCSPBatchResponse",
    "OCSPResponderInfo",
    "OCSPCreateResponderRequest",
    "OCSPResponderResponse",
    "OCSPStatsResponse",
    # Utils
    "beijing_now",
    "beijing_end_of_day",
    "format_datetime",
    "is_expired",
    "days_until_expiry",
]
