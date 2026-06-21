"""
证书相关的Pydantic Schema
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from .certificate_model import CertificateStatus, CertificateType


class CreateRootCertificateRequest(BaseModel):
    """创建根证书请求"""

    subject_name: str = Field(..., description="证书主体名称")
    validity_days: int = Field(3650, ge=1, le=7300, description="有效期天数，默认10年")


class CreateIntermediateCertificateRequest(BaseModel):
    """创建中间证书请求"""

    subject_name: str = Field(..., description="证书主体名称")
    parent_certificate_id: UUID = Field(..., description="父证书ID")
    validity_days: int = Field(1825, ge=1, le=3650, description="有效期天数，默认5年")


class CertificateBase(BaseModel):
    """证书基础Schema"""

    certificate_type: CertificateType
    subject: str
    issuer: str


class CertificateCreate(CertificateBase):
    """创建证书的Schema"""

    expires_at: datetime
    certificate_pem: str
    public_key: str
    parent_certificate_id: Optional[UUID] = None
    aic: Optional[str] = None


class CertificateUpdate(BaseModel):
    """更新证书的Schema"""

    status: Optional[CertificateStatus] = None
    revocation_reason: Optional[str] = None


class CertificateResponse(CertificateBase):
    """证书响应Schema"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    serial_number: str
    status: CertificateStatus
    issued_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    certificate_pem: str
    public_key: str
    parent_certificate_id: Optional[UUID] = None
    aic: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CertificateListResponse(BaseModel):
    """证书列表响应Schema"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    certificate_type: CertificateType
    serial_number: str
    subject: str
    issuer: str
    status: CertificateStatus
    issued_at: datetime
    expires_at: datetime
    aic: Optional[str] = None


class PagedResponse(BaseModel):
    """分页响应Schema"""

    items: List[CertificateListResponse]
    total: int
    page: int = Field(ge=1, description="当前页码")
    page_size: int = Field(ge=1, le=100, description="每页数量")
    total_pages: int


class ErrorResponse(BaseModel):
    """错误响应Schema"""

    error: str
    detail: Optional[str] = None
    code: Optional[str] = None
